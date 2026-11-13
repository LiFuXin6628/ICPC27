"""Stage 5: model-side probe of the measurement instrument (NOT human data).
For every mutant, ask a local model matched questions on the same input x* (a differing input):
  DESC     what does the ORIGINAL return for x*?                      truth: executed original output
  CF       if the code were changed as specified, what for x*?        truth: executed mutant output
  CF_CTRL  same counterfactual question on an input x0 whose result does NOT change   truth: original output
  DESC_MUT what does the (fully shown) MUTANT return for x*?          truth: executed mutant output
Accuracy by question type gives the instrument's difficulty ordering for models."""
import argparse
import os
import sys
sys.dont_write_bytecode = True   # never write __pycache__ (it would embed absolute paths)
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RESULTS, PROBE_MODELS, read_jsonl, write_jsonl, llm, extract_json  # noqa: E402
from prompts import SYSTEM_JSON, probe_prompt, probe_prompt_stripped, shortest  # noqa: E402
from check import claim_matches  # noqa: E402
from strip import stripped_pair  # noqa: E402
from execute import run_program  # noqa: E402
from common import outcomes_equal  # noqa: E402


def pick_inputs(rec):
    diff = shortest([e for e in rec["differing"] if e["orig"].get("exc") not in ("Timeout",)], 1)
    agree = shortest(rec["agreeing_examples"], 1)
    return (diff[0] if diff else None), (agree[0] if agree else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=PROBE_MODELS[0])
    ap.add_argument("--kinds", default="DESC,CF,CF_CTRL,DESC_MUT")
    ap.add_argument("--variant", default="docstring", choices=["docstring", "stripped"],
                    help="docstring = round-1 materials (original docstrings/names, raw line numbers); "
                         "stripped = round-2 materials (no docstrings/comments, entry renamed to f, shown line numbers)")
    args = ap.parse_args()
    mutants = [r for r in read_jsonl(os.path.join(RESULTS, "mutants.jsonl")) if r.get("op")]
    tag = args.model.replace(":", "_").replace("/", "_")
    prefix = "probe_" if args.variant == "docstring" else "probe_stripped_"
    out_path = os.path.join(RESULTS, f"{prefix}{tag}.jsonl")
    strip_cache = {}
    rows = {(r["id"], r["kind"]): r for r in read_jsonl(out_path)} if os.path.exists(out_path) else {}
    t0, n_new = time.time(), 0
    for kind in args.kinds.split(","):
        for i, rec in enumerate(mutants):
            key = (rec["id"], kind)
            if key in rows:
                continue
            xd, xa = pick_inputs(rec)
            if kind == "CF_CTRL":
                if xa is None:
                    continue
                inp, truth = xa["input"], xa["orig"]
            elif kind == "DESC":
                inp, truth = xd["input"], xd["orig"]
            else:  # CF, DESC_MUT
                inp, truth = xd["input"], xd["mut"]
            if args.variant == "stripped":
                if rec["id"] not in strip_cache:
                    so, sm, sdiff, sline = stripped_pair(rec)
                    ins = [x["input"] for x in (xd, xa) if x is not None]
                    oo = run_program(so, "f", ins, per_input_timeout=3.0, process_timeout=60)
                    mo = run_program(sm, "f", ins, per_input_timeout=3.0, process_timeout=60)
                    exp_o = [xd["orig"]] + ([xa["orig"]] if xa else [])
                    exp_m = [xd["mut"]] + ([xa["orig"]] if xa else [])
                    same = all(outcomes_equal(a, b) for a, b in zip(oo, exp_o)) and \
                        all(outcomes_equal(a, b) for a, b in zip(mo, exp_m))
                    strip_cache[rec["id"]] = (so, sm, sdiff, sline, same)
                so, sm, sdiff, sline, same = strip_cache[rec["id"]]
                prompt = probe_prompt_stripped(so, sm, sdiff, sline, kind, inp)
            else:
                prompt = probe_prompt(rec, kind, inp)
            resp = llm(prompt, model=args.model, system=SYSTEM_JSON, num_predict=300)
            j = extract_json(resp)
            answer = j.get("output") if isinstance(j, dict) else None
            correct = isinstance(j, dict) and "output" in j and claim_matches(answer, truth)
            # a CF answer that merely repeats the original output (ignores the intervention)
            repeats_original = (kind == "CF" and isinstance(j, dict) and claim_matches(answer, xd["orig"]))
            rows[key] = {"id": rec["id"], "op": rec["op"], "source": rec["source"], "model": args.model,
                         "kind": kind, "input": inp, "truth": truth, "answer": answer,
                         "parse_ok": isinstance(j, dict), "correct": bool(correct),
                         "repeats_original": bool(repeats_original), "response": resp[:500],
                         "variant": args.variant,
                         "strip_behaviour_preserved": strip_cache[rec["id"]][4] if args.variant == "stripped" else None}
            n_new += 1
            if n_new % 20 == 0:
                write_jsonl(out_path, list(rows.values()))
                print(f"  [{kind}] {i+1}/{len(mutants)} ({n_new} new, {time.time()-t0:.0f}s)", flush=True)
    write_jsonl(out_path, list(rows.values()))
    for kind in args.kinds.split(","):
        sub = [r for r in rows.values() if r["kind"] == kind]
        if sub:
            print(f"{args.model} {kind:8s} n={len(sub)} acc={sum(r['correct'] for r in sub)/len(sub):.3f}")


if __name__ == "__main__":
    main()
