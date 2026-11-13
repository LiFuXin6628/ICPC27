"""Planned-protocol materials (no LLM): a second, HELD-OUT intervention per function, so that human transfer items can
ask about a change the participant has not seen. A candidate qualifies only if (a) it edits a DIFFERENT LINE of the
shown (normalised) program than the explained mutant, (b) it is non-equivalent to the ORIGINAL on T, (c) it is
non-equivalent to the EXPLAINED MUTANT on T (so it is not the same intervention written differently, e.g.
`not a == b` vs `a != b`), and (d) it is not degenerate. Same seeded candidate order as build_mutants.py. Also records, for each held-out
mutant, affected and unaffected test inputs so that change-impact items can mix both (planned 50/50)."""
import os
import random
import sys
sys.dont_write_bytecode = True   # never write __pycache__ (it would embed absolute paths)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, RESULTS, SEED, MAX_CANDIDATES_TRIED, read_jsonl, write_jsonl  # noqa: E402
from execute import run_program, differential  # noqa: E402
from mutate import enumerate_candidates, apply  # noqa: E402
from build_mutants import _order_candidates, _degenerate, first_changed_line  # noqa: E402


def main():
    corpus = {c["id"]: c for c in read_jsonl(os.path.join(DATA, "corpus.jsonl"))}
    mutants = [m for m in read_jsonl(os.path.join(RESULTS, "mutants.jsonl")) if m.get("op")]
    rows = []
    for m in mutants:
        c = corpus[m["id"]]
        rng = random.Random(f"{SEED}-heldout-{c['id']}")
        cands = [k for k in enumerate_candidates(c["program"], c["entry_point"])
                 if not (k["op"] == m["op"] and k["line"] == m["line"])]
        orig_out = run_program(c["program"], c["entry_point"], c["inputs_repr"])
        expl_out = run_program(m["mutant"], c["entry_point"], c["inputs_repr"])
        rec = {"id": m["id"], "source": m["source"], "op": None, "rejected_same_line": 0, "rejected_same_behaviour": 0}
        for cand in _order_candidates(cands, rng)[:MAX_CANDIDATES_TRIED]:
            direction = rng.choice([1, -1]) if cand["op"] in ("DEF_ARG", "BOUND_CONST") else 1
            try:
                mutant, text, diff, _ = apply(c["program"], c["entry_point"], cand, direction)
            except Exception:
                continue
            if mutant == m["mutant"]:
                continue
            if first_changed_line(m["program"], mutant) == m["line_norm"]:
                rec["rejected_same_line"] += 1
                continue
            mut_out = run_program(mutant, c["entry_point"], c["inputs_repr"])
            idx = differential(orig_out, mut_out, c["set_compare"])
            if not idx or _degenerate(orig_out, mut_out, idx):
                continue
            if not differential(expl_out, mut_out, c["set_compare"]):
                rec["rejected_same_behaviour"] += 1
                continue
            agree = [i for i in range(len(orig_out)) if i not in set(idx) and orig_out[i].get("ok")]
            rec.update({"op": cand["op"], "intervention": text, "mutant": mutant, "diff": diff,
                        "line_norm": first_changed_line(m["program"], mutant),
                        "n_inputs": len(orig_out), "n_differ": len(idx),
                        "affected_inputs": [c["inputs_repr"][i] for i in idx[:4]],
                        "unaffected_inputs": [c["inputs_repr"][i] for i in agree[:4]]})
            break
        rows.append(rec)
    write_jsonl(os.path.join(RESULTS, "heldout_mutants.jsonl"), rows)
    ok = [r for r in rows if r["op"]]
    both = [r for r in ok if r["unaffected_inputs"]]
    print(f"held-out mutants: {len(ok)}/{len(rows)}; with both affected and unaffected inputs: {len(both)}")


if __name__ == "__main__":
    main()
