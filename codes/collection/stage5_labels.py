"""Stage 5: add Wikidata labels to the balanced temporal samples."""

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

import requests


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.config import PROCESSED, RAW, UA


API = "https://www.wikidata.org/w/api.php"
LANGUAGES = ("en", "mul", "ko")
ENTITY_ID = re.compile(r"^[QP][0-9]+$")
INPUT_NAME = "frequency_samples_up_to_100_per_class.jsonl"
OUTPUT_STEM = "frequency_samples_up_to_100_per_class_labeled"
FIELDS = [
    "entity",
    "entity_label",
    "relation",
    "relation_label",
    "value",
    "value_label",
    "frequency",
    "start_time",
    "end_time",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Resolve Wikidata IDs in the balanced samples to labels."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=PROCESSED / INPUT_NAME,
        help="Unlabeled Stage 4 JSONL file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROCESSED,
        help="Directory for labeled JSONL, CSV, and metadata.",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=RAW / "wikidata_label_cache.json",
        help="Reusable ID-to-label cache.",
    )
    parser.add_argument("--batch-size", type=int, default=50)
    return parser.parse_args()


def load_rows(path):
    if not path.exists():
        raise SystemExit(f"Input does not exist: {path}")
    rows = []
    with path.open(encoding="utf-8") as f:
        for line_number, line in enumerate(f, 1):
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Invalid JSON: {path}:{line_number}: {exc}") from exc
    return rows


def load_cache(path):
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SystemExit(f"Label cache must be a JSON object: {path}")
    return data


def save_cache(path, cache):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def select_label(entity_id, entity):
    labels = entity.get("labels", {})
    for language in LANGUAGES:
        label = labels.get(language)
        if label and label.get("value"):
            return label["value"]
    for language in sorted(labels):
        value = labels[language].get("value")
        if value:
            return value
    return entity_id


def request_entities(session, batch, languages):
    params = {
        "action": "wbgetentities",
        "ids": "|".join(batch),
        "props": "labels",
        "format": "json",
    }
    if languages:
        params["languages"] = "|".join(languages)
        params["languagefallback"] = "1"

    error = None
    for attempt in range(5):
        try:
            response = session.get(API, params=params, timeout=60)
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                raise RuntimeError(payload["error"])
            return payload.get("entities", {})
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            error = exc
            if attempt < 4:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"{batch[0]}..{batch[-1]}: {error}")


def fetch_labels(ids, cache, cache_path, batch_size):
    pending = sorted(entity_id for entity_id in ids if entity_id not in cache)
    session = requests.Session()
    session.headers.update(UA)
    fetched = 0

    for offset in range(0, len(pending), batch_size):
        batch = pending[offset : offset + batch_size]
        try:
            entities = request_entities(session, batch, LANGUAGES)
        except RuntimeError as exc:
            raise SystemExit(f"Label request failed for {exc}") from exc
        for entity_id in batch:
            cache[entity_id] = select_label(
                entity_id, entities.get(entity_id, {})
            )
        save_cache(cache_path, cache)
        fetched += len(batch)
        print(f"preferred labels: {fetched}/{len(pending)} fetched", flush=True)

    fallback = sorted(entity_id for entity_id in ids if cache.get(entity_id) == entity_id)
    fallback_batch_size = min(batch_size, 20)
    for offset in range(0, len(fallback), fallback_batch_size):
        batch = fallback[offset : offset + fallback_batch_size]
        try:
            entities = request_entities(session, batch, None)
        except RuntimeError as exc:
            raise SystemExit(f"Fallback label request failed for {exc}") from exc
        for entity_id in batch:
            cache[entity_id] = select_label(
                entity_id, entities.get(entity_id, {})
            )
        save_cache(cache_path, cache)
        fetched += len(batch)
        done = min(offset + len(batch), len(fallback))
        print(f"fallback labels: {done}/{len(fallback)} fetched", flush=True)

    return cache, fetched


def add_labels(rows, labels):
    result = []
    for row in rows:
        value = row["value"]
        value_label = labels.get(value, value) if ENTITY_ID.fullmatch(value) else value
        result.append(
            {
                "entity": row["entity"],
                "entity_label": labels.get(row["entity"], row["entity"]),
                "relation": row["relation"],
                "relation_label": labels.get(row["relation"], row["relation"]),
                "value": value,
                "value_label": value_label,
                "frequency": row["frequency"],
                "start_time": row["start_time"],
                "end_time": row.get("end_time"),
            }
        )
    return result


def write_outputs(rows, args, requested_ids, fetched_ids):
    args.output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = args.output_dir / f"{OUTPUT_STEM}.jsonl"
    csv_path = args.output_dir / f"{OUTPUT_STEM}.csv"
    meta_path = args.output_dir / f"{OUTPUT_STEM}.meta.json"

    with jsonl_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    unresolved = sorted(
        {
            entity_id
            for row in rows
            for entity_id, label in (
                (row["entity"], row["entity_label"]),
                (row["relation"], row["relation_label"]),
                (row["value"], row["value_label"]),
            )
            if ENTITY_ID.fullmatch(entity_id) and entity_id == label
        }
    )
    metadata = {
        "source": str(args.input),
        "wikidata_api": API,
        "label_language_priority": list(LANGUAGES),
        "label_fallback": "any available language, then original ID",
        "requested_unique_ids": len(requested_ids),
        "fetched_on_this_run": fetched_ids,
        "resolved_unique_ids": len(requested_ids) - len(unresolved),
        "unresolved_ids": unresolved,
        "total_records": len(rows),
        "fields": FIELDS,
    }
    source_meta_path = args.input.with_suffix(".meta.json")
    if source_meta_path.exists():
        with source_meta_path.open(encoding="utf-8") as f:
            source_meta = json.load(f)
        metadata["timeline_source"] = source_meta.get("source")
        for key in ("seed", "value_selection", "interval_selection", "interval_tie_break"):
            if key in source_meta:
                metadata[key] = source_meta[key]
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
        f.write("\n")

    return jsonl_path, csv_path, meta_path


def main():
    args = parse_args()
    if not 1 <= args.batch_size <= 50:
        raise SystemExit("--batch-size must be between 1 and 50")

    rows = load_rows(args.input)
    ids = {
        entity_id
        for row in rows
        for entity_id in (row["entity"], row["relation"], row["value"])
        if ENTITY_ID.fullmatch(entity_id)
    }
    cache = load_cache(args.cache)
    labels, fetched = fetch_labels(ids, cache, args.cache, args.batch_size)
    labeled_rows = add_labels(rows, labels)
    paths = write_outputs(labeled_rows, args, ids, fetched)

    print(f"labeled {len(labeled_rows)} records using {len(ids)} unique IDs")
    for path in paths:
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
