import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent

def fix_csv(filename):
    p = HERE / filename
    if not p.exists():
        return
    with p.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames

    for r in rows:
        if r["condition_arm"] == "counterfactual" and r["participant_id"].startswith("CO"):
            r["participant_id"] = "CF" + r["participant_id"][2:]

    with p.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Fixed {filename}")

fix_csv("human_study_responses.csv")
fix_csv("human_study_responses_filled.csv")
