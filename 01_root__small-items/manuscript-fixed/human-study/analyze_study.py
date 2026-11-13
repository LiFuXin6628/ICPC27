"""Score completed sessions against the frozen study key."""
import ast
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent
ARMS = ("code_only", "descriptive", "counterfactual")


def correct_answer(answer, expected):
    if not expected["ok"]:
        return answer.strip() == expected["exc"]
    try:
        predicted = ast.literal_eval(answer.strip())
    except (ValueError, SyntaxError):
        return False
    target = ast.literal_eval(expected["repr"])
    return type(predicted) is type(target) and predicted == target


def score_session(record, key):
    if record["protocol"] != key["protocol"] or not record.get("finished_at"):
        raise ValueError("wrong instrument version or unfinished session")
    expected = key["items"]
    seen = set()
    rows = defaultdict(list)
    for item in record["responses"]:
        item_id = item["item_id"]
        target = expected[item_id]
        if item_id in seen or any(item[k] != target[k] for k in ("task_id", "input_repr")):
            raise ValueError(f"duplicate or mismatched item {item_id}")
        seen.add(item_id)
        answer = item["answer"]
        confidence = item["confidence_pct"]
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError(f"missing answer for {item_id}")
        if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 100:
            raise ValueError(f"invalid confidence for {item_id}")
        correct = correct_answer(answer, target["outcome"])
        error = confidence / 100 - correct
        rows[target["kind"]].append((int(correct), error ** 2, error))
    if seen != expected.keys():
        raise ValueError("incomplete item set")
    result = {}
    for name, values in [("all", rows["affected"] + rows["unaffected"]), *rows.items()]:
        result[name] = tuple(mean(metric) for metric in zip(*values))
    return result


def main(directory):
    files = sorted(directory.glob("response_*.json"))
    if not files:
        print("No participant response exports found.")
        return
    key = json.loads((HERE / "study_key.json").read_text(encoding="utf-8"))
    participants = defaultdict(list)
    seen = set()
    for path in files:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            pid = record["participant_id"].strip()
            arm = record["arm"]
            if not pid or pid in seen or arm not in ARMS:
                raise ValueError("missing or duplicate participant ID or invalid arm")
            scores = score_session(record, key)
        except (TypeError, ValueError, KeyError) as error:
            raise SystemExit(f"{path.name}: {error}") from error
        seen.add(pid)
        participants[arm].append(scores)
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(["arm", "participants", "items", "input_group", "accuracy", "brier", "signed_confidence_error"])
    for arm in ARMS:
        group = participants[arm]
        if not group:
            continue
        for kind in ("all", "affected", "unaffected"):
            metrics = [mean(scores[kind][index] for scores in group) for index in range(3)]
            items = sum(kind == "all" or row["kind"] == kind for row in key["items"].values())
            writer.writerow([arm, len(group), len(group) * items, kind, *(f"{value:.4f}" for value in metrics)])


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "responses")
