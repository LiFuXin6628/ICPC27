"""Build study_data.json for the H2/H3 between-subjects human study from real artifact data.
Exports the qualifying near-transfer functions (non-broad, mixed held-out edit, certified grounded
predicate, Jaccard overlap <= 0.5) with docstrings stripped via artifact/src/strip.py.
"""
import csv
import difflib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REV = HERE.parent
ARTIFACT = REV.parent / "01_root__small-items" / "artifact"
sys.dont_write_bytecode = True
sys.path.insert(0, str(ARTIFACT / "src"))
from strip import strip_cues  # noqa: E402
from common import outcomes_equal  # noqa: E402
sys.path.insert(0, str(REV))
from extra_experiments import run_isolated  # noqa: E402

PROTOCOL = "near-transfer-v2"
SUMMARIES = {
    "HumanEvalP/20": "The original keeps the first adjacent pair with the smallest gap in the sorted list. The reference edit keeps the last such pair. The returned values differ when those pairs have different values.",
    "HumanEvalP/31": "For n > 1 with a nonempty candidate range, the original returns False on the first divisor. The reference edit returns False on the first candidate that is not a divisor. An empty range gives True in both versions.",
    "HumanEvalP/61": "The original rejects a negative running balance immediately. The reference edit checks only the final balance. A string with a negative prefix balance and zero final balance changes from False to True.",
}
WITNESSES = {"HumanEvalP/20": "[[1.5, 2.5, 3.5, 4.5]]",
             "HumanEvalP/31": "[11]", "HumanEvalP/61": "[')(']"}


def show_diff(before, after):
    return "\n".join(difflib.unified_diff(before.splitlines(), after.splitlines(),
                                          "original", "edited", lineterm=""))


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def main():
    corpus = {r["id"]: r for r in read_jsonl(ARTIFACT / "data" / "corpus.jsonl")}
    mutants = {r["id"]: r for r in read_jsonl(ARTIFACT / "results" / "mutants.jsonl") if r.get("op")}
    heldout = {r["id"]: r for r in read_jsonl(ARTIFACT / "results" / "heldout_mutants.jsonl") if r.get("op")}
    preds = {(r["id"], r["condition"]): r for r in read_jsonl(ARTIFACT / "results" / "predicates_claude-haiku-5-5.jsonl")}

    eligible_ids = []
    with (REV / "transfer-overlap.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["passes_overlap_cap"] == "True":
                eligible_ids.append(row["id"])

    tasks = []
    key = {}
    for idx, tid in enumerate(eligible_ids, start=1):
        c = corpus[tid]
        m1 = mutants[tid]
        m2 = heldout[tid]
        p = preds[(tid, "grounded")]

        # Strip docstrings & rename entry point to f for consistent presentation
        stripped_orig = strip_cues(c["program"], c["entry_point"])
        stripped_m1 = strip_cues(m1["mutant"], c["entry_point"])
        stripped_m2 = strip_cues(m2["mutant"], c["entry_point"])

        # Pick 1 affected and 1 unaffected input for the held-out unseen edit
        aff_in = m2["affected_inputs"][0]
        unaff_in = m2["unaffected_inputs"][0]

        inputs = [aff_in, unaff_in]
        set_compare = bool(c.get("set_compare", False))
        if not p.get("exact"):
            raise ValueError(f"{tid}: reference predicate is not exact on T")
        before = run_isolated(stripped_orig, "f", inputs)
        after = run_isolated(stripped_m2, "f", inputs)
        for kind, raw, orig, changed in zip(("affected", "unaffected"), inputs, before, after):
            if not orig["ok"] or not changed["ok"] or (kind == "affected") == outcomes_equal(orig, changed, set_compare):
                raise ValueError(f"{tid}: unexpected outcome for {raw}")
            key[f"{tid}_{kind}"] = {"task_id": tid, "kind": kind, "input_repr": raw, "outcome": changed}
        witness = WITNESSES[tid]
        w_before, = run_isolated(stripped_orig, "f", [witness])
        w_after, = run_isolated(stripped_m1, "f", [witness])
        if witness in inputs or not w_before["ok"] or not w_after["ok"] or outcomes_equal(w_before, w_after, set_compare):
            raise ValueError(f"{tid}: invalid reference witness")
        tasks.append({
            "id": tid,
            "label": f"Task {idx}",
            "entry_point": c["entry_point"],
            "stripped_orig": stripped_orig,
            "shown_edit_intervention": m1["intervention"],
            "shown_edit_diff": show_diff(stripped_orig, stripped_m1),
            "descriptive_prose": SUMMARIES[tid],
            "counterfactual": {
                "witness_input": witness,
                "original_output": w_before["repr"],
                "mutant_output": w_after["repr"],
                "affected_predicate": p.get("code", ""),
            },
            "unseen_edit_intervention": m2["intervention"],
            "unseen_edit_diff": show_diff(stripped_orig, stripped_m2),
            "unseen_mutant_code": stripped_m2,
            "items": [
                {"item_id": f"{tid}_affected", "kind": "affected", "input_repr": aff_in},
                {"item_id": f"{tid}_unaffected", "kind": "unaffected", "input_repr": unaff_in},
            ],
        })

    out = {
        "protocol": PROTOCOL,
        "arms": ["code_only", "descriptive", "counterfactual"],
        "n_tasks": len(tasks),
        "tasks": tasks,
    }
    out_path = HERE / "study_data.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    (HERE / "study_key.json").write_text(json.dumps({"protocol": PROTOCOL, "items": key}, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out_path} with {len(tasks)} tasks: {[t['id'] for t in tasks]}")


if __name__ == "__main__":
    main()

