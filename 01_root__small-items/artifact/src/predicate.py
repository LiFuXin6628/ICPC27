"""Round-2 stage: the affected-input claim A as an EXECUTABLE predicate.
Each generator writes `affected(<args>) -> bool` ("True iff ORIGINAL and MUTANT differ on these arguments"), with
(grounded) or without (ungrounded) the execution evidence. The predicate is executed in the sandbox on every test
input of T and scored against the
executed difference set Delta_T (primary: all of T; sensitivity: T without the inputs shown in the grounded
prompt). Metrics per function: exact (all inputs classified correctly), balanced accuracy
(mean of the per-class recalls; plain accuracy when T has one class), precision/recall/F1 on "affected".
LLM-written predicates are untrusted code: they pass a static check (no imports except math/itertools/functools/
collections/re/string, no open/eval/exec/__import__/getattr dunder access) and then run in the process-isolated sandbox.
"""
import argparse
import ast
import os
import random
import re
import sys
sys.dont_write_bytecode = True   # never write __pycache__ (it would embed absolute paths)
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RESULTS, SEED, GEN_MODEL, STRONG_MODEL, read_jsonl, write_jsonl, llm  # noqa: E402
from prompts import predicate_prompt, shown_inputs  # noqa: E402
from execute import run_program  # noqa: E402

SYSTEM_CODE = "You are a precise program-comprehension assistant. You answer with one Python code block and no other text."
ALLOWED_IMPORTS = {"math", "itertools", "functools", "collections", "re", "string", "operator"}
BANNED_NAMES = {"open", "eval", "exec", "compile", "__import__", "input", "globals", "locals", "vars", "breakpoint",
                "getattr", "setattr", "delattr", "exit", "quit"}
STRONG_SUBSET_N = 72      # Haiku predicates on a seeded random subset (API budget)


def signature(rec):
    tree = ast.parse(rec["program"])
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == rec["entry_point"]:
            a = n.args
            names = [x.arg for x in a.posonlyargs + a.args]
            if a.vararg:
                names.append("*" + a.vararg.arg)
            return "(" + ", ".join(names) + ")"
    return "(*args)"


def extract_code(text):
    if not text:
        return None
    m = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    code = m[0] if m else text
    return code if "def affected" in code else None


def static_check(code):
    """Return (ok, reason, n_lines, defines_inner)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False, "syntax", 0, False
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "affected"]
    if not fns:
        return False, "no-affected", 0, False
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            mods = [a.name.split(".")[0] for a in n.names] if isinstance(n, ast.Import) else [(n.module or "").split(".")[0]]
            if any(mm not in ALLOWED_IMPORTS for mm in mods):
                return False, "banned-import", 0, False
        if isinstance(n, ast.Name) and n.id in BANNED_NAMES:
            return False, "banned-name", 0, False
        if isinstance(n, ast.Attribute) and n.attr.startswith("__"):
            return False, "dunder", 0, False
    body_lines = len([l for l in ast.unparse(fns[0]).splitlines()[1:] if l.strip()])
    inner = any(isinstance(n, (ast.FunctionDef, ast.Lambda)) and n is not fns[0] for n in ast.walk(fns[0]))
    return True, "ok", body_lines, inner


def _metrics(pred, valid, truth):
    tp = sum(1 for p, t, v in zip(pred, truth, valid) if v and p and t)
    tn = sum(1 for p, t, v in zip(pred, truth, valid) if v and not p and not t)
    fp = sum(1 for p, t, v in zip(pred, truth, valid) if v and p and not t)
    npos, nneg = sum(truth), len(truth) - sum(truth)
    recs = ([tp / npos] if npos else []) + ([tn / nneg] if nneg else [])
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec_ = tp / npos if npos else float("nan")
    f1 = 2 * prec * rec_ / (prec + rec_) if npos and prec + rec_ else 0.0
    return {"n_scored": len(truth), "n_pos": npos, "n_neg": nneg, "tp": tp, "tn": tn, "fp": fp,
            "fn": npos - tp, "n_invalid": sum(1 for v in valid if not v), "exact": (tp + tn) == len(truth),
            "bal_acc": sum(recs) / len(recs) if recs else float("nan"), "precision": prec, "recall": rec_, "f1": f1}


def score(rec, code):
    """Primary: all of T. Sensitivity: T minus the inputs shown in the grounded prompt (same set in both conditions)."""
    inputs = rec["_all_inputs"]
    diff_set = {e["input"] for e in rec["differing"]}
    truth = [i in diff_set for i in inputs]
    out = run_program(code, "affected", inputs, per_input_timeout=1.0, process_timeout=60)
    pred = [bool(o.get("ok")) and o.get("repr") in ("True", "1") for o in out]
    valid = [bool(o.get("ok")) and o.get("repr") in ("True", "False", "1", "0") for o in out]
    res = _metrics(pred, valid, truth)
    shown = set(shown_inputs(rec))
    keep = [k for k, i in enumerate(inputs) if i not in shown]
    sens = _metrics([pred[k] for k in keep], [valid[k] for k in keep], [truth[k] for k in keep])
    res.update({f"unshown_{k}": v for k, v in sens.items()})
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=GEN_MODEL)
    ap.add_argument("--conditions", default="ungrounded,grounded")
    args = ap.parse_args()
    corpus = {r["id"]: r for r in read_jsonl(os.path.join(os.path.dirname(RESULTS), "data", "corpus.jsonl"))}
    mutants = [r for r in read_jsonl(os.path.join(RESULTS, "mutants.jsonl")) if r.get("op")]
    if args.model == STRONG_MODEL:
        ids = sorted(r["id"] for r in mutants)
        keep = set(random.Random(f"{SEED}-predicate-subset").sample(ids, STRONG_SUBSET_N))
        mutants = [r for r in mutants if r["id"] in keep]
    tag = args.model.replace(":", "_").replace("/", "_")
    out_path = os.path.join(RESULTS, f"predicates_{tag}.jsonl")
    rows = {(r["id"], r["condition"]): r for r in read_jsonl(out_path)} if os.path.exists(out_path) else {}
    t0, n_new = time.time(), 0
    for cond in args.conditions.split(","):
        for i, rec in enumerate(mutants):
            key = (rec["id"], cond)
            if key in rows:
                continue
            prompt = predicate_prompt(rec, cond == "grounded", signature(rec))
            resp = llm(prompt, model=args.model, system=SYSTEM_CODE, num_predict=600)
            code = extract_code(resp)
            r = {"id": rec["id"], "op": rec["op"], "source": rec["source"], "model": args.model, "condition": cond,
                 "response": resp, "code": code, "n_differ": rec["n_differ"], "n_inputs": rec["n_inputs"]}
            if code is None:
                r.update({"status": "no-code", "exact": False, "bal_acc": 0.0, "f1": 0.0})
            else:
                ok, reason, nl, inner = static_check(code)
                r.update({"body_lines": nl, "defines_inner": inner})
                if not ok:
                    r.update({"status": reason, "exact": False, "bal_acc": 0.0, "f1": 0.0})
                else:
                    rec = dict(rec, _all_inputs=corpus[rec["id"]]["inputs_repr"][:rec["n_inputs"]])
                    r.update(score(rec, code))
                    r["status"] = "scored"
            rows[key] = r
            n_new += 1
            if n_new % 10 == 0:
                write_jsonl(out_path, list(rows.values()))
                print(f"  [{cond}] {i+1}/{len(mutants)} ({n_new} new, {time.time()-t0:.0f}s)", flush=True)
    write_jsonl(out_path, list(rows.values()))
    for cond in args.conditions.split(","):
        sub = [r for r in rows.values() if r["condition"] == cond]
        if sub:
            print(f"{args.model} {cond:10s} n={len(sub)} exact={sum(r['exact'] for r in sub)/len(sub):.3f} "
                  f"bal_acc={sum(r['bal_acc'] for r in sub)/len(sub):.3f}")


if __name__ == "__main__":
    main()
