"""Default: inspect storage. --execute: download the original paper assets."""
import argparse
import gzip
import json
import os
import shutil
from protocol import BASE, MODEL, MODEL_REVISION, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    assets = BASE / "assets"
    present = sum(p.stat().st_size for p in assets.rglob("*") if p.is_file()) if assets.exists() else 0
    required = max(0, 220 * 1024**3 - present)
    free = shutil.disk_usage(BASE).free
    report = {"free_bytes": free, "conservative_additional_space_bytes": required,
              "index_bytes": 64559075373, "model_safetensors_bytes": 30462504632,
              "compressed_corpus_bytes": 5123307260, "ready_for_download": free >= required,
              "note": "220 GiB is a conservative setup budget including index parts, assembled index, corpus expansion, environment and caches; not an exact measured peak."}
    write_json(BASE / "reference/storage_preflight.json", report)
    print(json.dumps(report, indent=2))
    if not args.execute:
        return
    if free < required:
        raise SystemExit("Insufficient space for original assets; no downloads started.")
    from run import environment
    os.environ.update(environment())
    from huggingface_hub import HfApi, hf_hub_download, snapshot_download
    lock = BASE / "reference/assets.lock.json"
    if lock.exists():
        revisions = json.loads(lock.read_text())
    else:
        api = HfApi()
        revisions = {"model": MODEL_REVISION, "e5": "f52bf8ec8c7124536f0efb74aca902b2995e5bcd",
                     "index": api.dataset_info("PeterJinGo/wiki-18-e5-index").sha,
                     "corpus": api.dataset_info("PeterJinGo/wiki-18-corpus").sha}
        write_json(lock, revisions)
    for name, repo in [("model", MODEL), ("e5", "intfloat/e5-base-v2")]:
        snapshot_download(repo_id=repo, revision=revisions[name], local_dir=assets / name,
                          allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.tiktoken"])
    for part in ["part_aa", "part_ab"]:
        hf_hub_download("PeterJinGo/wiki-18-e5-index", filename=part, repo_type="dataset",
                        revision=revisions["index"], local_dir=assets / "index")
    combined = assets / "index/e5_Flat.index"
    if not combined.exists():
        temporary = combined.with_suffix(".partial")
        with temporary.open("wb") as out:
            for part in ["part_aa", "part_ab"]:
                with (assets / "index" / part).open("rb") as source:
                    shutil.copyfileobj(source, out, length=8 * 1024**2)
        if temporary.stat().st_size != 64559075373:
            raise ValueError("Unexpected concatenated index size")
        temporary.replace(combined)
    compressed = hf_hub_download("PeterJinGo/wiki-18-corpus", filename="wiki-18.jsonl.gz", repo_type="dataset",
                                 revision=revisions["corpus"], local_dir=assets / "corpus")
    corpus = assets / "corpus/wiki-18.jsonl"
    if not corpus.exists():
        temporary = corpus.with_suffix(".partial")
        with gzip.open(compressed, "rb") as source, temporary.open("wb") as out:
            shutil.copyfileobj(source, out, length=8 * 1024**2)
        temporary.replace(corpus)


if __name__ == "__main__":
    main()
