"""Stage 4: sample a balanced set of entity-property timelines.

Sample timelines first so that entities with long histories are not
overrepresented. Then select one value interval from each sampled timeline to
produce (entity, relation, value, frequency, start_time, end_time) records.
"""

import argparse
import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.config import PROCESSED, RAW


CLASSES = [
    "A-Day",
    "A-Few-Days",
    "A-Week",
    "A-Few-Weeks",
    "A-Month",
    "A-Few-Months",
    "A-Year",
    "A-Few-Years",
    "Many-Years",
]
FIELDS = ["entity", "relation", "value", "frequency", "start_time", "end_time"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Sample temporal statement records evenly by frequency class."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=RAW / "wd_scan" / "timelines.before_overlapfix",
        help="Directory containing Stage 3 property JSONL files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROCESSED,
        help="Directory for the sampled JSONL, CSV, and metadata files.",
    )
    parser.add_argument("--per-class", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def reservoir_sample(input_dir, per_class, seed):
    """Uniformly sample unique entity-property timelines by frequency class."""
    rng = random.Random(seed)
    samples = {name: [] for name in CLASSES}
    candidate_counts = Counter()
    duplicate_counts = Counter()
    seen = {name: set() for name in CLASSES}

    paths = sorted(input_dir.glob("*.jsonl"), key=lambda p: int(p.stem[1:]))
    if not paths:
        raise SystemExit(f"No timeline JSONL files found in {input_dir}")

    for path in paths:
        with path.open(encoding="utf-8") as f:
            for line_number, line in enumerate(f, 1):
                try:
                    timeline = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise SystemExit(f"Invalid JSON: {path}:{line_number}: {exc}") from exc

                frequency = timeline.get("frequency_class")
                if frequency not in samples:
                    continue

                key = (timeline["subject"], timeline["property"], frequency)
                if key in seen[frequency]:
                    duplicate_counts[frequency] += 1
                    continue
                seen[frequency].add(key)

                candidate_counts[frequency] += 1
                n = candidate_counts[frequency]
                bucket = samples[frequency]
                if len(bucket) < per_class:
                    bucket.append(timeline)
                else:
                    replacement = rng.randrange(n)
                    if replacement < per_class:
                        bucket[replacement] = timeline

    rows = []
    for name in CLASSES:
        class_rows = []
        for timeline in samples[name]:
            intervals = timeline.get("timeline", [])
            if not intervals:
                raise SystemExit(
                    f"Timeline has no intervals: {timeline[subject]} "
                    f"{timeline[property]}"
                )
            interval = rng.choice(intervals)
            class_rows.append(
                {
                    "entity": timeline["subject"],
                    "relation": timeline["property"],
                    "value": interval["value"],
                    "frequency": name,
                    "start_time": interval["start"],
                    "end_time": interval.get("end"),
                }
            )
        rng.shuffle(class_rows)
        rows.extend(class_rows)
    return rows, candidate_counts, duplicate_counts, len(paths)


def write_outputs(rows, candidate_counts, duplicate_counts, n_files, args):
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"frequency_samples_up_to_{args.per_class}_per_class"
    jsonl_path = args.output_dir / f"{stem}.jsonl"
    csv_path = args.output_dir / f"{stem}.csv"
    meta_path = args.output_dir / f"{stem}.meta.json"

    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    sample_counts = Counter(row["frequency"] for row in rows)
    metadata = {
        "source": str(args.input_dir),
        "sampling_unit": "entity_property_timeline",
        "sampling_method": "uniform reservoir sampling without replacement",
        "value_selection": "one uniformly random interval per sampled timeline",
        "seed": args.seed,
        "maximum_per_class": args.per_class,
        "classes": CLASSES,
        "source_files": n_files,
        "candidate_counts": {name: candidate_counts[name] for name in CLASSES},
        "duplicate_timelines_skipped": {
            name: duplicate_counts[name] for name in CLASSES
        },
        "sample_counts": {name: sample_counts[name] for name in CLASSES},
        "total_samples": len(rows),
        "fields": FIELDS,
    }
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
        f.write("\n")

    return jsonl_path, csv_path, meta_path


def main():
    args = parse_args()
    if args.per_class <= 0:
        raise SystemExit("--per-class must be positive")

    rows, candidate_counts, duplicate_counts, n_files = reservoir_sample(
        args.input_dir, args.per_class, args.seed
    )
    paths = write_outputs(rows, candidate_counts, duplicate_counts, n_files, args)

    sample_counts = Counter(row["frequency"] for row in rows)
    print(f"sampled {len(rows)} entity-property timelines")
    for name in CLASSES:
        print(
            f"  {name:<16} candidates={candidate_counts[name]:>8,} "
            f"sampled={sample_counts[name]}"
        )
    for path in paths:
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
