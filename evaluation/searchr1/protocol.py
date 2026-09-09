"""Frequency Bench adapter; model receives only the original CSV query."""

import csv
import hashlib
import io
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
MODEL = "PeterJinGo/SearchR1-nq_hotpotqa_train-qwen2.5-7b-em-ppo-v0.2"
MODEL_REVISION = "053b6e1addc3affc5bf7e920b654b8ac9610c7ba"
UPSTREAM_REVISION = "598e61bd1d36895726d28a8d06b3a15bed19f5d3"

# Official scripts/data_process/nq_search.py, make_prefix(template_type='base').
PREFIX = (
    "Answer the given question. "
    "You must conduct reasoning inside <think> and </think> first every time you get new information. "
    "After reasoning, if you find you lack some knowledge, you can call a search engine by <search> query </search> "
    "and it will return the top searched results between <information> and </information>. "
    "You can search as many times as your want. "
    "If you find no further external knowledge needed, you can directly provide the answer inside <answer> and </answer>, "
    "without detailed illustrations. For example, <answer> Beijing </answer>. Question: "
)


def load_rows(path):
    raw = path.read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    required = {"entity_id", "property_id", "query", "value", "frequency"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError(f"Required columns: {sorted(required)}")
    rows = list(reader)
    if not rows:
        raise ValueError("Input is empty")
    seen = set()
    for i, row in enumerate(rows):
        if None in row or any(v is None for v in row.values()):
            raise ValueError(f"Malformed CSV row {i + 1}")
        if any(not row[k].strip() for k in required):
            raise ValueError(f"Empty required field in row {i + 1}")
        sample_id = row["entity_id"] + ":" + row["property_id"]
        if sample_id in seen:
            raise ValueError(f"Duplicate entity-property pair: {sample_id}")
        seen.add(sample_id)
        row = dict(row, sample_id=sample_id, source_index=i)
        rows[i] = row
    return rows, hashlib.sha256(raw).hexdigest()


def adapt(row):
    return {
        "data_source": "frequency_bench",
        "prompt": [{"role": "user", "content": PREFIX + row["query"] + "\n"}],
        "ability": "fact-reasoning",
        "reward_model": {"style": "rule", "ground_truth": {"target": [row["value"]]}},
        "extra_info": dict(row, split="test", index=row["source_index"]),
    }


def pilot_rows(rows, count=10, seed=42):
    groups = defaultdict(list)
    for row in rows:
        groups[row["frequency"]].append(row)
    rng = random.Random(seed)
    chosen = {r["sample_id"] for group in groups.values() for r in rng.sample(group, min(count, len(group)))}
    return [row for row in rows if row["sample_id"] in chosen]


def summarize(expected, records):
    expected_ids = {r["sample_id"] for r in expected}
    record_ids = [r["sample_id"] for r in records]
    if len(record_ids) != len(set(record_ids)):
        raise ValueError("Duplicate predictions; use a fresh run directory")
    if set(record_ids) - expected_ids:
        raise ValueError("Predictions do not belong to this evaluation set")
    by_id = {r["sample_id"]: r for r in records}
    totals = Counter(r["frequency"] for r in expected)
    groups = {}
    for frequency, count in totals.items():
        group = [by_id[r["sample_id"]] for r in expected if r["frequency"] == frequency and r["sample_id"] in by_id]
        groups[frequency] = {
            "expected": count, "evaluated": len(group),
            "correct": sum(r["em"] for r in group),
            "accuracy": sum(r["em"] for r in group) / len(group) if group else None,
        }
    complete = set(record_ids) == expected_ids
    return {
        "metric": "official_normalized_em_against_csv_value",
        "complete": complete,
        "expected": len(expected), "evaluated": len(records),
        "missing_ids": sorted(expected_ids - set(record_ids)),
        "micro_accuracy": sum(r["em"] for r in records) / len(records) if records else None,
        "macro_accuracy": sum(g["accuracy"] for g in groups.values()) / len(groups) if complete else None,
        "by_frequency": groups,
        "note": "Partial-run accuracy is over evaluated rows only. CSV historical value agreement is not an adjudication of all valid answers to an undated query.",
    }


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
