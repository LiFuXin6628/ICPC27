"""CPU-only follow-up experiments:
1. Deterministic differential-testing baseline (no LLM) on all 129 mutants.
2. Out-of-T generalization check for all cached Qwen (129) and Haiku (72) predicates.
Runs all untrusted/mutated/generated code in isolated `python -I` subprocesses.
"""
import ast
import copy
import csv
import json
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARTIFACT = HERE.parent / "01_root__small-items" / "artifact"
sys.dont_write_bytecode = True
sys.path.insert(0, str(ARTIFACT / "src"))
from common import outcomes_equal  # noqa: E402

SEED = 20261112
N_FRESH_TARGET = 50
SUBPROCESS_TIMEOUT = 8.0

# Worker executed in an isolated `python -I` subprocess.
# Receives JSON on stdin:
#   {"program": str, "entry_point": str, "inputs_repr": [str, ...]}
# Outputs JSON list of outcomes:
#   {"ok": true, "repr": str} | {"ok": false, "exc": str}
_WORKER_CODE = r"""
import ast, contextlib, io, json, math, sys, threading

_ALLOWED = {"inf": math.inf, "nan": math.nan, "True": True, "False": False, "None": None}

def _parse(s):
    tree = ast.parse(s, mode="eval")
    def ev(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name) and node.id in _ALLOWED:
            return _ALLOWED[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = ev(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.List):
            return [ev(e) for e in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(ev(e) for e in node.elts)
        if isinstance(node, ast.Set):
            return set(ev(e) for e in node.elts)
        if isinstance(node, ast.Dict):
            return {ev(k): ev(v) for k, v in zip(node.keys, node.values)}
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and \
                node.func.id in ("set", "frozenset", "tuple", "list", "dict") and len(node.args) <= 1:
            arg = ev(node.args[0]) if node.args else []
            return {"set": set, "frozenset": frozenset, "tuple": tuple, "list": list, "dict": dict}[node.func.id](arg)
        raise ValueError("disallowed")
    return ev(tree.body)

def main():
    job = json.load(sys.stdin)
    sys.setrecursionlimit(1500)
    g = {"__name__": "__sandbox__"}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(job["program"], "<program>", "exec"), g)
        fn = g[job["entry_point"]]
    except BaseException as e:
        json.dump([{"ok": False, "exc": "LoadError:" + type(e).__name__}] * len(job["inputs_repr"]), sys.stdout)
        return
    outcomes = []
    for s in job["inputs_repr"]:
        try:
            args = _parse(s)
        except Exception:
            outcomes.append({"ok": False, "exc": "InputParseError"})
            continue
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                out = fn(*args)
            r = repr(out)
            if len(r) > 4000:
                r = r[:200] + f"...len={len(r)}"
            outcomes.append({"ok": True, "repr": r})
        except BaseException as e:
            outcomes.append({"ok": False, "exc": type(e).__name__})
    json.dump(outcomes, sys.stdout)

if __name__ == "__main__":
    main()
"""


def run_isolated(program: str, entry_point: str, inputs_repr: list[str]) -> list[dict]:
    if not inputs_repr:
        return []
    payload = json.dumps({"program": program, "entry_point": entry_point, "inputs_repr": inputs_repr})
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", _WORKER_CODE],
            input=payload,
            text=True,
            capture_output=True,
            timeout=SUBPROCESS_TIMEOUT,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return json.loads(proc.stdout)
    except subprocess.TimeoutExpired:
        # Fall back to smaller batches or mark timeout if a loop hangs.
        if len(inputs_repr) > 1:
            mid = len(inputs_repr) // 2
            return (run_isolated(program, entry_point, inputs_repr[:mid]) +
                    run_isolated(program, entry_point, inputs_repr[mid:]))
        return [{"ok": False, "exc": "Timeout"}]
    except Exception:
        pass
    return [{"ok": False, "exc": "RunnerError"} for _ in inputs_repr]


def parse_safe(s: str):
    return ast.literal_eval(s)


def mutate_value(val, rng: random.Random):
    """Generate a type-preserving fresh value from an example value."""
    if isinstance(val, bool):
        return rng.choice([True, False])
    if isinstance(val, int):
        return rng.choice([0, 1, -1, 2, -2, 3, 5, 7, 10, 100, val + rng.choice([-3, -1, 1, 2, 5]), rng.randint(-50, 100)])
    if isinstance(val, float):
        return rng.choice([0.0, 1.0, -1.0, 0.5, -0.5, round(val + rng.uniform(-5.0, 5.0), 3), round(rng.uniform(-20.0, 20.0), 2)])
    if isinstance(val, str):
        if not val:
            return rng.choice(["", "a", "ab", "0", " ", "()"])
        chars = list(set(val)) + ["a", "b", "0", "1", " ", "(", ")"]
        length = rng.choice([0, 1, max(1, len(val) - 1), len(val), len(val) + 1, rng.randint(1, 8)])
        return "".join(rng.choice(chars) for _ in range(length))
    if isinstance(val, list):
        if not val:
            return rng.choice([[], [0], [1, 2], [-1, 0, 1]])
        length = rng.choice([0, 1, 2, max(1, len(val) - 1), len(val), len(val) + 1])
        return [mutate_value(rng.choice(val), rng) for _ in range(length)]
    if isinstance(val, tuple):
        return tuple(mutate_value(v, rng) for v in val)
    if isinstance(val, dict):
        if not val:
            return {}
        items = list(val.items())
        k = rng.randint(0, len(items))
        return {mutate_value(items[i][0], rng): mutate_value(items[i][1], rng) for i in range(k)}
    if isinstance(val, set):
        if not val:
            return set()
        lst = list(val)
        return {mutate_value(rng.choice(lst), rng) for _ in range(rng.randint(0, len(lst) + 1))}
    return copy.deepcopy(val)


def generate_fresh_inputs(existing_reprs: list[str], n_target: int, rng: random.Random) -> list[str]:
    existing_set = set(existing_reprs)
    parsed_examples = []
    for s in existing_reprs[:30]:
        try:
            parsed_examples.append(parse_safe(s))
        except Exception:
            continue
    if not parsed_examples:
        return []
    fresh = []
    seen = set(existing_set)
    attempts = 0
    while len(fresh) < n_target and attempts < n_target * 25:
        attempts += 1
        template = rng.choice(parsed_examples)
        candidate = [mutate_value(arg, rng) for arg in template]
        r = repr(candidate)
        if r not in seen:
            seen.add(r)
            fresh.append(r)
    return fresh


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def main():
    rng = random.Random(SEED)
    corpus = {r["id"]: r for r in read_jsonl(ARTIFACT / "data" / "corpus.jsonl")}
    mutants = {r["id"]: r for r in read_jsonl(ARTIFACT / "results" / "mutants.jsonl") if r.get("op")}
    preds_haiku = {(r["id"], r["condition"]): r for r in read_jsonl(ARTIFACT / "results" / "predicates_claude-haiku-5-5.jsonl")}
    preds_qwen = {(r["id"], r["condition"]): r for r in read_jsonl(ARTIFACT / "results" / "predicates_qwen2.5-coder_14b.jsonl")}

    diff_rows = []
    out_of_t_rows = []

    for idx, (tid, m) in enumerate(sorted(mutants.items()), start=1):
        c = corpus[tid]
        ep = c["entry_point"]
        set_cmp = bool(c.get("set_compare", False))
        fresh_reprs = generate_fresh_inputs(c["inputs_repr"], N_FRESH_TARGET, rng)

        orig_outs = run_isolated(c["program"], ep, fresh_reprs)
        mut_outs = run_isolated(m["mutant"], ep, fresh_reprs)

        # Keep inputs where neither side timed out / failed to parse
        valid_indices = [
            i for i, (o1, o2) in enumerate(zip(orig_outs, mut_outs))
            if o1.get("exc") not in ("Timeout", "InputParseError", "RunnerError")
            and o2.get("exc") not in ("Timeout", "InputParseError", "RunnerError")
        ]
        valid_fresh = [fresh_reprs[i] for i in valid_indices]
        differ_flags = [
            not outcomes_equal(orig_outs[i], mut_outs[i], set_compare=set_cmp)
            for i in valid_indices
        ]

        first_witness_idx = next((k + 1 for k, d in enumerate(differ_flags) if d), None)
        diff_rows.append({
            "id": tid,
            "op": m["op"],
            "n_fresh_valid": len(valid_fresh),
            "n_fresh_differ": sum(differ_flags),
            "found_in_10": int(first_witness_idx is not None and first_witness_idx <= 10),
            "found_in_25": int(first_witness_idx is not None and first_witness_idx <= 25),
            "found_in_50": int(first_witness_idx is not None and first_witness_idx <= 50),
            "first_witness_eval": first_witness_idx if first_witness_idx is not None else "",
        })

        # Evaluate cached predicates on valid_fresh
        for model_name, pmap in (("qwen2.5-coder_14b", preds_qwen), ("claude-haiku-5-5", preds_haiku)):
            for cond in ("ungrounded", "grounded"):
                rec = pmap.get((tid, cond))
                if rec is None:
                    continue
                scorable = (rec.get("status") == "scored" and rec.get("n_invalid", 0) < rec.get("n_scored", 0))
                if not scorable or not rec.get("code") or not valid_fresh:
                    out_of_t_rows.append({
                        "model": model_name,
                        "id": tid,
                        "condition": cond,
                        "in_t_exact": int(bool(rec.get("exact", False))),
                        "scorable": int(scorable),
                        "n_fresh": len(valid_fresh),
                        "n_fresh_differ": sum(differ_flags),
                        "n_pred_valid": 0,
                        "out_of_t_exact": 0,
                        "out_of_t_fp": 0,
                        "out_of_t_fn": 0,
                    })
                    continue

                p_outs = run_isolated(rec["code"], "affected", valid_fresh)
                fp = fn = inv = 0
                for po, truth in zip(p_outs, differ_flags):
                    if not po.get("ok"):
                        inv += 1
                        continue
                    r = po.get("repr")
                    if r not in ("True", "False"):
                        inv += 1
                        continue
                    pred = (r == "True")
                    if pred and not truth:
                        fp += 1
                    elif not pred and truth:
                        fn += 1
                exact_fresh = int(inv == 0 and fp == 0 and fn == 0 and len(valid_fresh) > 0)
                out_of_t_rows.append({
                    "model": model_name,
                    "id": tid,
                    "condition": cond,
                    "in_t_exact": int(bool(rec.get("exact", False))),
                    "scorable": 1,
                    "n_fresh": len(valid_fresh),
                    "n_fresh_differ": sum(differ_flags),
                    "n_pred_valid": len(valid_fresh) - inv,
                    "out_of_t_exact": exact_fresh,
                    "out_of_t_fp": fp,
                    "out_of_t_fn": fn,
                })
        if idx % 25 == 0:
            print(f"Processed {idx}/{len(mutants)} mutants...", flush=True)

    with (HERE / "diff_testing_baseline.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(diff_rows[0]))
        w.writeheader()
        w.writerows(diff_rows)

    with (HERE / "out_of_t_generalization.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_of_t_rows[0]))
        w.writeheader()
        w.writerows(out_of_t_rows)

    # Print summary
    n_mut = len(diff_rows)
    print(f"\n=== Differential Testing Baseline (n={n_mut}) ===")
    for k in ("found_in_10", "found_in_25", "found_in_50"):
        cnt = sum(r[k] for r in diff_rows)
        print(f"  {k}: {cnt}/{n_mut} ({100*cnt/n_mut:.1f}%)")

    print("\n=== Out-of-T Generalization ===")
    for model_name in ("qwen2.5-coder_14b", "claude-haiku-5-5"):
        for cond in ("ungrounded", "grounded"):
            sub = [r for r in out_of_t_rows if r["model"] == model_name and r["condition"] == cond]
            with_fresh = [r for r in sub if r["n_fresh"] > 0]
            in_t = sum(r["in_t_exact"] for r in with_fresh)
            out_t = sum(r["out_of_t_exact"] for r in with_fresh)
            both = sum(1 for r in with_fresh if r["in_t_exact"] and r["out_of_t_exact"])
            print(f"  {model_name} [{cond}] (n={len(with_fresh)}): in_T_exact={in_t}, out_of_T_exact={out_t}, both_exact={both}/{in_t}")


if __name__ == "__main__":
    main()
