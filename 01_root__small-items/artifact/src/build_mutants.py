"""Stage 2: for each corpus function, try candidate mutants in a seeded order until one is
NON-equivalent on the test inputs (differential execution in the sandbox). Records the selected
mutant, the differing inputs with both outcomes (the executed counterfactual), and bookkeeping:
candidates tried, equivalent candidates, non-terminating / degenerate candidates."""
import json
import os
import random
import sys
sys.dont_write_bytecode = True   # never write __pycache__ (it would embed absolute paths)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, RESULTS, SEED, MAX_CANDIDATES_TRIED, read_jsonl, write_jsonl, outcome_str  # noqa: E402
from execute import run_program, differential  # noqa: E402
from mutate import enumerate_candidates, apply, OPERATORS  # noqa: E402


def _order_candidates(cands, rng):
    """Seeded order that balances operators: shuffle operators, then round-robin over sites."""
    by_op = {}
    for c in cands:
        by_op.setdefault(c["op"], []).append(c)
    ops = [o for o in OPERATORS if o in by_op]
    rng.shuffle(ops)
    for o in ops:
        rng.shuffle(by_op[o])
    ordered = []
    while any(by_op[o] for o in ops):
        for o in ops:
            if by_op[o]:
                ordered.append(by_op[o].pop())
    return ordered


def first_changed_line(a, b):
    """1-based line number, in the normalised (shown) ORIGINAL, of the first line the mutant changes.
    (`line` keeps the raw-source line number used by the round-1 probe prompts, which was wrong for 82/129.)"""
    la, lb = a.splitlines(), b.splitlines()
    for i, (x, y) in enumerate(zip(la, lb)):
        if x != y:
            return i + 1
    return min(len(la), len(lb)) + 1


def _degenerate(orig_out, mut_out, diff_idx):
    """A mutant is degenerate if it fails on every input with the same exception (e.g. NameError),
    or if the sandbox crashed / timed out at process level."""
    if any(o.get("exc") in ("ProcessTimeout", "ProcessCrash") or (o.get("exc") or "").startswith("LoadError")
           for o in mut_out):
        return "process-failure"
    if any(o.get("exc") == "Timeout" for o in mut_out) and not any(o.get("exc") == "Timeout" for o in orig_out):
        return "non-terminating"
    if len(diff_idx) == len(mut_out) and all(not o.get("ok") for o in mut_out) and \
            len({o.get("exc") for o in mut_out}) == 1:
        return "crashes-everywhere"
    return None


def main():
    corpus = read_jsonl(os.path.join(DATA, "corpus.jsonl"))
    out_path = os.path.join(RESULTS, "mutants.jsonl")
    done = {r["id"]: r for r in read_jsonl(out_path)} if os.path.exists(out_path) else {}
    rows = []
    stats = {"functions": 0, "with_mutant": 0, "candidates_tried": 0, "equivalent": 0,
             "non_terminating": 0, "crashes_everywhere": 0, "process_failure": 0, "no_candidates": 0,
             "original_failed": 0}
    for fi, c in enumerate(corpus):
        stats["functions"] += 1
        if c["id"] in done:
            r = done[c["id"]]
            rows.append(r)
            for k in ("candidates_tried", "equivalent", "non_terminating", "crashes_everywhere",
                      "process_failure"):
                stats[k] += r["bookkeeping"].get(k, 0)
            if r.get("op"):
                stats["with_mutant"] += 1
            elif r["bookkeeping"].get("reason") == "no_candidates":
                stats["no_candidates"] += 1
            elif r["bookkeeping"].get("reason") == "original_failed":
                stats["original_failed"] += 1
            continue
        rng = random.Random(f"{SEED}-{c['id']}")
        orig_out = run_program(c["program"], c["entry_point"], c["inputs_repr"])
        bk = {"candidates_tried": 0, "equivalent": 0, "non_terminating": 0, "crashes_everywhere": 0,
              "process_failure": 0}
        rec = {"id": c["id"], "source": c["source"], "entry_point": c["entry_point"], "op": None,
               "bookkeeping": bk}
        n_orig_ok = sum(1 for o in orig_out if o.get("ok"))
        if n_orig_ok < max(3, len(orig_out) // 2):
            bk["reason"] = "original_failed"
            stats["original_failed"] += 1
            rows.append(rec)
            print(f"[{fi+1}/{len(corpus)}] {c['id']}: original failed ({n_orig_ok}/{len(orig_out)} ok)")
            continue
        cands = enumerate_candidates(c["program"], c["entry_point"])
        if not cands:
            bk["reason"] = "no_candidates"
            stats["no_candidates"] += 1
            rows.append(rec)
            print(f"[{fi+1}/{len(corpus)}] {c['id']}: no candidates")
            continue
        ordered = _order_candidates(cands, rng)[:MAX_CANDIDATES_TRIED]
        chosen = None
        for cand in ordered:
            direction = rng.choice([1, -1]) if cand["op"] in ("DEF_ARG", "BOUND_CONST") else 1
            try:
                mutant, text, diff, orig_norm = apply(c["program"], c["entry_point"], cand, direction)
            except Exception as e:
                continue
            bk["candidates_tried"] += 1
            mut_out = run_program(mutant, c["entry_point"], c["inputs_repr"])
            diff_idx = differential(orig_out, mut_out, c["set_compare"])
            deg = _degenerate(orig_out, mut_out, diff_idx)
            if deg == "non-terminating":
                bk["non_terminating"] += 1
                continue
            if deg == "crashes-everywhere":
                bk["crashes_everywhere"] += 1
                continue
            if deg == "process-failure":
                bk["process_failure"] += 1
                continue
            if not diff_idx:
                bk["equivalent"] += 1
                continue
            chosen = (cand, mutant, text, diff, orig_norm, mut_out, diff_idx)
            break
        for k in ("candidates_tried", "equivalent", "non_terminating", "crashes_everywhere", "process_failure"):
            stats[k] += bk[k]
        if chosen is None:
            bk["reason"] = "no_nonequivalent_mutant"
            rows.append(rec)
            print(f"[{fi+1}/{len(corpus)}] {c['id']}: no non-equivalent mutant among {bk['candidates_tried']}")
            continue
        cand, mutant, text, diff, orig_norm, mut_out, diff_idx = chosen
        agree_idx = [i for i in range(len(orig_out)) if i not in set(diff_idx) and orig_out[i].get("ok")]
        rec.update({
            "op": cand["op"], "intervention": text, "line": cand["line"], "line_norm": first_changed_line(orig_norm, mutant),
            "program": orig_norm,
            "mutant": mutant, "diff": diff, "n_inputs": len(orig_out), "n_differ": len(diff_idx),
            "set_compare": c["set_compare"],
            "differing": [{"input": c["inputs_repr"][i], "orig": orig_out[i], "mut": mut_out[i]} for i in diff_idx],
            "agreeing_examples": [{"input": c["inputs_repr"][i], "orig": orig_out[i]} for i in agree_idx[:5]],
            "n_cands_available": len(cands),
        })
        stats["with_mutant"] += 1
        rows.append(rec)
        ex = rec["differing"][0]
        print(f"[{fi+1}/{len(corpus)}] {c['id']}: {cand['op']} differs on {len(diff_idx)}/{len(orig_out)} "
              f"e.g. {ex['input'][:50]} -> {outcome_str(ex['orig'], 40)} / {outcome_str(ex['mut'], 40)}")
        write_jsonl(out_path, rows)  # checkpoint
    write_jsonl(out_path, rows)
    with open(os.path.join(RESULTS, "mutation_stats.json"), "w") as f:
        json.dump(stats, f, indent=1)
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
