"""Stage 4: score every explanation against the executed counterfactual.

(a) PROGRAMMATIC check: the explanation's claimed witness input is executed on ORIGINAL and MUTANT in the
    sandbox. It passes iff the witness parses, the two versions really differ on it, and the claimed
    ORIGINAL and MUTANT outputs match the executed ones (tolerant comparison; exceptions by type).
    In the grounded condition a witness copied from the shown evidence is flagged (copied=True).
(b) JUDGE check: two LLM judges from families other than the generator's grade the prose fields
    (affected_inputs, difference) against the executed ground truth. Judge error = either field wrong.
"""
import argparse
import json
import os
import re
import sys
sys.dont_write_bytecode = True   # never write __pycache__ (it would embed absolute paths)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (RESULTS, JUDGE_MODELS, read_jsonl, write_jsonl, llm, extract_json, try_literal,  # noqa: E402
                    outcomes_equal, _close)
from execute import run_program  # noqa: E402
from prompts import SYSTEM_JSON, judge_prompt, shown_inputs, n_params  # noqa: E402

_EXC_RE = re.compile(r"\b([A-Z][A-Za-z]*(?:Error|Exception|Exit|Interrupt|Warning))\b")


def canon(x):
    """Canonical form so that JSON (from the model) and Python literals (from execution) compare."""
    if isinstance(x, bool) or x is None or isinstance(x, (int, float, str)):
        return x
    if isinstance(x, (list, tuple)):
        return [canon(v) for v in x]
    if isinstance(x, (set, frozenset)):
        return sorted((canon(v) for v in x), key=repr)
    if isinstance(x, dict):
        return {"__dict__": sorted(([str(canon(k)), canon(v)] for k, v in x.items()), key=repr)}
    return repr(x)


def claim_matches(claim, outcome):
    """Does the model's claimed output (JSON value or 'raises X') match the executed outcome?"""
    if not outcome.get("ok"):
        if not isinstance(claim, str):
            return False
        names = _EXC_RE.findall(claim)
        if names:
            return outcome.get("exc") in names
        return bool(re.search(r"raise|error|exception", claim, re.I))
    if isinstance(claim, str) and re.search(r"^\s*raises?\b", claim, re.I):
        return False
    ok, actual = try_literal(outcome["repr"])
    if not ok:
        return isinstance(claim, str) and claim.strip() == outcome["repr"].strip()
    if isinstance(claim, str) and not isinstance(actual, str):
        ok2, v = try_literal(claim)   # model wrote the value as a string literal
        if ok2:
            claim = v
    if isinstance(actual, str) and not isinstance(claim, str):
        return False
    if isinstance(actual, str):
        if claim == actual:
            return True
        ok3, v3 = try_literal(claim)   # model wrapped the string in an extra level of quotes, e.g. '"An"'
        return ok3 and isinstance(v3, str) and v3 == actual
    return _close(canon(claim), canon(actual))


def witness_args(parsed, program, entry_point):
    """Candidate argument tuples for the model's witness. For a one-parameter function a witness such as
    ["abc"] is ambiguous (argument "abc", or the list ["abc"] as the single argument); both readings are
    returned and the checker accepts the explanation if EITHER reading passes (lenient scoring)."""
    w = parsed.get("witness_input")
    if isinstance(w, str):
        ok, v = try_literal(w)
        if not ok:
            return None
        w = v
    if isinstance(w, dict):
        return None
    np_, varargs = n_params(program, entry_point)
    if not isinstance(w, (list, tuple)):
        w = [w]
    w = list(w)
    if np_ == 1 and not varargs:
        if len(w) != 1:
            return [repr([w])]
        return [repr(w), repr([w])]
    return [repr(w)]


def programmatic(rec, exp):
    out = {"parse_ok": exp["parse_ok"], "witness_ok": False, "witness_differs": False,
           "orig_claim_correct": False, "mut_claim_correct": False, "copied": False}
    if not exp["parse_ok"]:
        out["error"] = True
        out["failure"] = "unparsable"
        return out
    p = exp["parsed"]
    cands = witness_args(p, rec["program"], rec["entry_point"])
    if cands is None:
        out["error"] = True
        out["failure"] = "no-witness"
        return out
    out["witness_ok"] = True
    shown = set()
    for s in shown_inputs(rec):
        ok_s, sv = try_literal(s)
        if ok_s:
            shown.add(repr(canon(sv)))
    best = None
    for w in cands:
        ok, wv = try_literal(w)
        o = run_program(rec["program"], rec["entry_point"], [w], per_input_timeout=3.0, process_timeout=30)[0]
        m = run_program(rec["mutant"], rec["entry_point"], [w], per_input_timeout=3.0, process_timeout=30)[0]
        r = {"witness_repr": w, "orig_outcome": o, "mut_outcome": m,
             "copied": exp["condition"] == "grounded" and repr(canon(wv)) in shown,
             "witness_differs": not outcomes_equal(o, m, rec.get("set_compare", False)),
             "orig_claim_correct": claim_matches(p.get("original_output"), o),
             "mut_claim_correct": claim_matches(p.get("mutant_output"), m)}
        r["error"] = not (r["witness_differs"] and r["orig_claim_correct"] and r["mut_claim_correct"])
        score = (not r["error"], r["witness_differs"], r["orig_claim_correct"])
        if best is None or score > best[0]:
            best = (score, r)
        if not r["error"]:
            break
    out.update(best[1])
    out["n_readings"] = len(cands)
    if out["error"]:
        o_, m_ = out.get("orig_outcome", {}), out.get("mut_outcome", {})
        malformed = (not out["witness_differs"]) and not o_.get("ok") and not m_.get("ok") and \
            o_.get("exc") == m_.get("exc")
        out["failure"] = ("malformed-witness" if malformed else   # same exception on both: input-encoding error
                          "witness-not-differing" if not out["witness_differs"] else
                          "wrong-original-output" if not out["orig_claim_correct"] else "wrong-mutant-output")
    else:
        out["failure"] = "none"
    return out


def judge(rec, exp, model):
    if not exp["parse_ok"]:
        return {"model": model, "error": True, "affected_inputs_correct": False, "difference_correct": False,
                "false_claim": True, "parse_ok": False}
    p = exp["parsed"]
    prompt = judge_prompt(rec, str(p.get("affected_inputs", "")), str(p.get("difference", "")))
    resp = llm(prompt, model=model, system=SYSTEM_JSON, num_predict=300)
    j = extract_json(resp)
    if not isinstance(j, dict):
        return {"model": model, "error": True, "parse_ok": False, "response": resp}
    a = bool(j.get("affected_inputs_correct")) if isinstance(j.get("affected_inputs_correct"), bool) else \
        str(j.get("affected_inputs_correct")).lower().startswith("t")
    d = bool(j.get("difference_correct")) if isinstance(j.get("difference_correct"), bool) else \
        str(j.get("difference_correct")).lower().startswith("t")
    fc = j.get("false_claim")
    fc = fc if isinstance(fc, bool) else str(fc).lower().startswith("t")
    return {"model": model, "parse_ok": True, "affected_inputs_correct": a, "difference_correct": d,
            "false_claim": fc, "error": not (a and d), "rationale": str(j.get("rationale", ""))[:300]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--explanations", required=True, help="explanations_<model>.jsonl")
    ap.add_argument("--judges", default=",".join(JUDGE_MODELS))
    ap.add_argument("--skip-judges", action="store_true")
    ap.add_argument("--recheck", action="store_true", help="recompute the programmatic check, keep judge results")
    args = ap.parse_args()
    mutants = {r["id"]: r for r in read_jsonl(os.path.join(RESULTS, "mutants.jsonl")) if r.get("op")}
    exps = read_jsonl(os.path.join(RESULTS, args.explanations))
    out_path = os.path.join(RESULTS, args.explanations.replace("explanations_", "scores_"))
    done = {(r["id"], r["condition"]): r for r in read_jsonl(out_path)} if os.path.exists(out_path) else {}
    judges = [] if args.skip_judges else [j for j in args.judges.split(",") if j]
    rows = []
    for i, exp in enumerate(exps):
        rec = mutants[exp["id"]]
        key = (exp["id"], exp["condition"])
        r = done.get(key) or {"id": exp["id"], "op": exp["op"], "source": rec["source"], "model": exp["model"],
                              "condition": exp["condition"], "n_differ": rec["n_differ"], "n_inputs": rec["n_inputs"]}
        if args.recheck or "programmatic" not in r:
            r["programmatic"] = programmatic(rec, exp)
        r.setdefault("judges", {})
        for jm in judges:
            if jm not in r["judges"]:
                r["judges"][jm] = judge(rec, exp, jm)
        rows.append(r)
        if (i + 1) % 10 == 0:   # checkpoint: processed rows + not-yet-processed earlier rows (no truncation)
            seen = {(x["id"], x["condition"]) for x in rows}
            write_jsonl(out_path, rows + [v for k, v in done.items() if k not in seen])
            print(f"  {i+1}/{len(exps)}", flush=True)
    write_jsonl(out_path, rows)
    for cond in ("ungrounded", "grounded"):
        sub = [r for r in rows if r["condition"] == cond]
        pe = sum(r["programmatic"]["error"] for r in sub)
        line = f"{cond:10s} n={len(sub)} programmatic-error={pe/len(sub):.3f}"
        for jm in judges:
            je = sum(r["judges"][jm]["error"] for r in sub)
            line += f"  judge[{jm}]-error={je/len(sub):.3f}"
        print(line)


if __name__ == "__main__":
    main()
