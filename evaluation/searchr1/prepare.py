"""Read the original CSV without modification; prepare full and pilot evaluations."""

import argparse
import json
from collections import Counter

from protocol import BASE, ROOT, MODEL, MODEL_REVISION, UPSTREAM_REVISION, adapt, load_rows, pilot_rows, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", action="store_true", help="Also write native Search-R1 inputs (requires pyarrow)")
    args = parser.parse_args()
    rows, digest = load_rows(ROOT / "data/final/frequency_bench.csv")
    target = BASE / "data"
    target.mkdir(exist_ok=True)
    for name, selected in [("full", rows), ("pilot", pilot_rows(rows))]:
        examples = [adapt(row) for row in selected]
        with (target / f"{name}.jsonl").open("w", encoding="utf-8") as output:
            for example in examples:
                output.write(json.dumps(example, ensure_ascii=False) + "\n")
        if args.parquet:
            import pyarrow as pa
            import pyarrow.parquet as pq
            pq.write_table(pa.Table.from_pylist(examples), target / f"{name}.parquet")
    manifest = {
        "input": "../../data/final/frequency_bench.csv", "input_sha256": digest,
        "rows": len(rows), "pilot_rows": len(pilot_rows(rows)),
        "frequency_counts": dict(Counter(r["frequency"] for r in rows)),
        "model": MODEL, "model_revision": MODEL_REVISION,
        "upstream_revision": UPSTREAM_REVISION,
        "question": "original query column, unchanged", "gold": "value column, one target string",
        "corpus": "PeterJinGo/wiki-18-corpus", "index": "PeterJinGo/wiki-18-e5-index (Flat)",
        "retriever": "intfloat/e5-base-v2", "topk": 3, "do_sample": False,
        "max_turns": 4, "final_generation_after_turns": True,
        "max_start_length": 2048, "max_prompt_length": 4096,
        "max_response_length": 500, "max_obs_length": 500,
        "pilot_seed": 42, "pilot_per_frequency": 10,
    }
    write_json(target / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
