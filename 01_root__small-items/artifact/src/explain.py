"""Stage 3: generate counterfactual explanations with a local model (and an optional stronger model)
under two conditions: A = ungrounded (code + diff), B = execution-grounded (code + diff + evidence).
Every call is temperature 0, seeded, cached under results/llm_cache/."""
import argparse
import json
import os
import sys
sys.dont_write_bytecode = True   # never write __pycache__ (it would embed absolute paths)
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RESULTS, GEN_MODEL, read_jsonl, write_jsonl, llm, extract_json  # noqa: E402
from prompts import SYSTEM_JSON, explain_prompt  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=GEN_MODEL)
    ap.add_argument("--conditions", default="ungrounded,grounded")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    mutants = [r for r in read_jsonl(os.path.join(RESULTS, "mutants.jsonl")) if r.get("op")]
    if args.limit:
        mutants = mutants[:args.limit]
    tag = args.model.replace(":", "_").replace("/", "_")
    out_path = os.path.join(RESULTS, f"explanations_{tag}.jsonl")
    rows = {(r["id"], r["condition"]): r for r in read_jsonl(out_path)} if os.path.exists(out_path) else {}
    t0 = time.time()
    n_new = 0
    for cond in args.conditions.split(","):
        for i, rec in enumerate(mutants):
            key = (rec["id"], cond)
            if key in rows:
                continue
            prompt = explain_prompt(rec, grounded=(cond == "grounded"))
            resp = llm(prompt, model=args.model, system=SYSTEM_JSON, num_predict=700)
            parsed = extract_json(resp)
            rows[key] = {"id": rec["id"], "op": rec["op"], "model": args.model, "condition": cond,
                         "response": resp, "parsed": parsed, "parse_ok": isinstance(parsed, dict)}
            n_new += 1
            if n_new % 10 == 0:
                write_jsonl(out_path, list(rows.values()))
                print(f"  [{cond}] {i+1}/{len(mutants)} ({n_new} new, {time.time()-t0:.0f}s)", flush=True)
    write_jsonl(out_path, list(rows.values()))
    ok = sum(1 for r in rows.values() if r["parse_ok"])
    print(f"{args.model}: {len(rows)} explanations, {ok} parsed as JSON -> results/{os.path.basename(out_path)}")


if __name__ == "__main__":
    main()
