"""Run official Search-R1 inference and scoring; keep artifacts below this directory."""
import argparse
import datetime
import importlib.util
import json
import os
import shlex
import subprocess
import sys
from protocol import BASE, ROOT, load_rows, summarize, write_json


def environment():
    env = os.environ.copy()
    for key, suffix in {
        "HF_HOME": "cache/huggingface", "XDG_CACHE_HOME": "cache", "TORCH_HOME": "cache/torch",
        "PIP_CACHE_DIR": "cache/pip", "TMPDIR": "tmp", "RAY_TMPDIR": "tmp",
        "WANDB_DIR": "results/wandb", "TRITON_CACHE_DIR": "cache/triton", "CUDA_CACHE_PATH": "cache/cuda",
    }.items():
        path = BASE / suffix
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    env["PYTHONPATH"] = os.pathsep.join([str(BASE), str(BASE / "upstream"), env.get("PYTHONPATH", "")])
    env.update(VLLM_ATTENTION_BACKEND="XFORMERS", PYTHONUNBUFFERED="1", WANDB_MODE="disabled")
    return env


def build_command(split, gpu_count, batch_size, result_dir):
    source = (BASE / "reference/scripts/nq_hotpotqa/evaluate.sh").read_text()
    source = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    args = shlex.split(source.split("python3 -m verl.trainer.main_ppo", 1)[1].replace("\\\n", " "))
    args = [a.replace("$DATA_DIR/train.parquet", str(BASE / "data/full.parquet"))
             .replace("$DATA_DIR/test.parquet", str(BASE / f"data/{split}.parquet"))
             .replace("$BASE_MODEL", str(BASE / "assets/model")) for a in args]
    overrides = {"data.val_batch_size": str(batch_size), "trainer.n_gpus_per_node": str(gpu_count),
                 "critic.model.path": str(BASE / "assets/model"),
                 "trainer.default_local_dir": str(result_dir / "checkpoints")}
    args = [a for a in args if a.split("=", 1)[0] not in overrides]
    args.extend(f"{k}={v}" for k, v in overrides.items())
    args.extend([f"hydra.run.dir={result_dir / 'hydra'}", "hydra.output_subdir=null"])
    return [sys.executable, "-m", "verl.trainer.main_ppo", *args]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["pilot", "full"], default="pilot")
    parser.add_argument("--gpus", default="0")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    gpu_count = len(args.gpus.split(","))
    if args.batch_size <= 0 or args.batch_size % gpu_count:
        parser.error("Batch size must be positive and divisible by GPU count")
    manifest = json.loads((BASE / "data/manifest.json").read_text())
    _, digest = load_rows(ROOT / "data/final/frequency_bench.csv")
    if digest != manifest["input_sha256"]:
        raise ValueError("CSV changed; rerun prepare.py --parquet")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    result_dir = BASE / "results" / f"{args.split}-{stamp}"
    command = build_command(args.split, gpu_count, args.batch_size, result_dir)
    print(shlex.join(command))
    if args.dry_run:
        return
    paths = [BASE / "assets/model/config.json", BASE / "data/full.parquet", BASE / f"data/{args.split}.parquet"]
    missing = [str(p) for p in paths if not p.exists()]
    missing += [m for m in ["torch", "vllm", "ray", "hydra", "pyarrow"] if importlib.util.find_spec(m) is None]
    if missing:
        raise SystemExit("Missing prerequisites: " + ", ".join(missing))
    env = environment()
    env["CUDA_VISIBLE_DEVICES"] = args.gpus
    env["SEARCHR1_RESULT_PATH"] = str(result_dir / "predictions.jsonl")
    result_dir.mkdir(parents=True, exist_ok=False)
    write_json(result_dir / "manifest.json", dict(manifest, split=args.split, command=command,
               gpus=args.gpus, batch_size=args.batch_size, started_at=stamp))
    with (result_dir / "packages.txt").open("w") as output:
        subprocess.run([sys.executable, "-m", "pip", "freeze"], stdout=output, check=True, env=env)
    status = 1
    try:
        with (result_dir / "evaluation.log").open("w") as output:
            status = subprocess.run(command, cwd=BASE / "upstream", env=env, stdout=output, stderr=subprocess.STDOUT).returncode
    finally:
        examples = [json.loads(line) for line in (BASE / f"data/{args.split}.jsonl").read_text().splitlines()]
        predictions = result_dir / "predictions.jsonl"
        records = [json.loads(line) for line in predictions.read_text().splitlines()] if predictions.exists() else []
        summary = summarize([ex["extra_info"] for ex in examples], records)
        summary["process_exit_code"] = status
        write_json(result_dir / "summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"Results: {result_dir}")
    if status or not summary["complete"]:
        raise SystemExit(status or 1)


if __name__ == "__main__":
    main()
