"""Use each sampled triple's first source interval, preserving all other fields.

Dry run: python codes/preprocessing/update_sample_intervals.py
Apply:   python codes/preprocessing/update_sample_intervals.py --write
The existing JSONL, CSV and metadata are validated before any output is written.
No sampling, label lookup or frequency recalculation is performed.
"""

import argparse
import csv
import json
from pathlib import Path

from stage4_timelines import (
    INTERVAL_SELECTION, INTERVAL_TIE_BREAK, earliest_interval_for_value,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "data/processed/frequency_samples_up_to_100_per_class_labeled.jsonl"
DEFAULT_SOURCE = ROOT / "data/raw/wd_scan/timelines.before_overlapfix"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    with args.input.open(encoding="utf-8") as f:
        original = [json.loads(line) for line in f]
    if not original:
        raise ValueError("Input dataset is empty")
    fields = list(original[0])
    csv_path = args.input.with_suffix(".csv")
    meta_path = args.input.with_suffix(".meta.json")
    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        csv_rows = list(reader)
        assert reader.fieldnames == fields, "CSV schema differs from JSONL"
    expected_csv = [{k: "" if v is None else str(v) for k, v in row.items()}
                    for row in original]
    assert csv_rows == expected_csv, "CSV contents differ from JSONL"
    with meta_path.open(encoding="utf-8") as f:
        metadata = json.load(f)
    assert metadata["total_records"] == len(original)
    wanted = {(row["entity"], row["relation"]) for row in original}
    timelines = {}
    for pid in sorted({r["relation"] for r in original}, key=lambda p: int(p[1:])):
        with (args.source / (pid + ".jsonl")).open(encoding="utf-8") as f:
            for line in f:
                timeline = json.loads(line)
                key = (timeline["subject"], timeline["property"])
                if key in wanted:
                    if key in timelines:
                        raise ValueError(f"Duplicate source timeline: {key}")
                    timelines[key] = timeline
    assert timelines.keys() == wanted, "Source timelines are missing"
    updated, changes = [], []
    for row in original:
        timeline = timelines[(row["entity"], row["relation"])]
        assert timeline["frequency_class"] == row["frequency"]
        assert any(i["value"] == row["value"] and i["start"] == row["start_time"]
                   and i.get("end") == row["end_time"] for i in timeline["timeline"]), row
        first = earliest_interval_for_value(timeline["timeline"], row["value"])
        new = {**row, "start_time": first["start"], "end_time": first.get("end")}
        updated.append(new)
        if new != row:
            changes.append({"entity": row["entity_label"], "relation": row["relation_label"],
                            "value": row["value_label"],
                            "before": [row["start_time"], row["end_time"]],
                            "after": [new["start_time"], new["end_time"]]})
    metadata.update({"timeline_source": str(args.source.resolve()),
                     "interval_selection": INTERVAL_SELECTION,
                     "interval_tie_break": INTERVAL_TIE_BREAK})
    if args.write:
        # Stage complete outputs before replacing their corresponding files.
        jsonl_tmp = args.input.with_suffix(".jsonl.tmp")
        csv_tmp = csv_path.with_suffix(".csv.tmp")
        meta_tmp = meta_path.with_suffix(".json.tmp")
        with jsonl_tmp.open("w", encoding="utf-8") as f:
            for row in updated:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        with csv_tmp.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(updated)
        with meta_tmp.open("w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
            f.write("\n")
        jsonl_tmp.replace(args.input)
        csv_tmp.replace(csv_path)
        meta_tmp.replace(meta_path)
    print(json.dumps({"written": args.write, "records": len(original),
                      "changed": len(changes), "examples": changes[:5]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
