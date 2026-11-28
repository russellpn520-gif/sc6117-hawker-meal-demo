"""Join the two saved responses per image and score identical cohorts, without any model call."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from statistics import mean

NUTRIENTS = ("kcal", "protein_g", "carb_g", "fat_g")
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()
    folder = args.ledger
    prefix = "release" if args.release else "paired"
    with (HERE / f"{prefix}_samples.csv").open(encoding="utf-8") as f:
        samples = list(csv.DictReader(f))
    rows = []
    for sample in samples:
        row = {"id": sample["id"], "food": sample["name"]}
        for nutrient in NUTRIENTS:
            row["reference_" + nutrient] = float(sample[nutrient])
        for arm in ("direct", "pipeline"):
            response = json.loads((folder / (sample["id"] + "-" + arm + ".json")).read_bytes())
            if response.get("sha256", sample["sha256"]) != sample["sha256"]:
                raise ValueError(f"Ledger image differs from manifest for {sample['id']}")
            row[arm + "_status"] = response["status"]
            usage = response.get("usage") or {}
            for field in ("input_tokens", "output_tokens"):
                row[arm + "_" + field] = usage.get(field)
            row[arm + "_model"] = response.get("model")
            if arm == "pipeline":
                row["matched_items"] = json.dumps(response.get("items", []), ensure_ascii=False)
                row["missing_items"] = json.dumps(response.get("missing", []), ensure_ascii=False)
                if args.release:
                    row["pipeline_label"] = json.dumps(response["label"], ensure_ascii=False) if "label" in response else ""
            for nutrient in NUTRIENTS:
                value = (response.get("prediction") or {}).get(nutrient)
                row[arm + "_" + nutrient] = round(value, 5) if value is not None else None
                row[arm + "_error_" + nutrient] = round(value - row["reference_" + nutrient], 5) if value is not None else None
        rows.append(row)
    with (HERE / f"{prefix}_results.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for prefix in ("H", "P"):
        cohort = [r for r in rows if r["id"].startswith(prefix)]
        print(prefix, Counter(r["pipeline_status"] for r in cohort))
        for status in ({"complete", "partial"}, {"complete"}):
            matched = [r for r in cohort if r["pipeline_status"] in status and r["direct_status"] == "complete"]
            print("paired", sorted(status), len(matched))
            for arm in ("direct", "pipeline"):
                if matched:
                    print(arm, [round(mean(abs(r[arm + "_error_" + n]) for r in matched), 3) for n in NUTRIENTS])
        for arm in ("direct", "pipeline"):
            print(arm, "input/output", [sum(r[arm + "_" + k] or 0 for r in cohort) for k in ("input_tokens", "output_tokens")])


if __name__ == "__main__":
    main()
