"""Launch the original E5 Flat GPU search server."""
import argparse
import subprocess
import sys
from protocol import BASE
from run import environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpus", default="1")
    args = parser.parse_args()
    paths = [BASE / "assets/index/e5_Flat.index", BASE / "assets/corpus/wiki-18.jsonl", BASE / "assets/e5/config.json"]
    if any(not p.exists() for p in paths):
        raise SystemExit("Download assets first; see README.md")
    env = environment()
    env["CUDA_VISIBLE_DEVICES"] = args.gpus
    command = [sys.executable, str(BASE / "upstream/search_r1/search/retrieval_server.py"),
               "--index_path", str(paths[0]), "--corpus_path", str(paths[1]),
               "--retriever_model", str(BASE / "assets/e5"), "--retriever_name", "e5", "--topk", "3", "--faiss_gpu"]
    with (BASE / "results/retriever.log").open("a") as output:
        raise SystemExit(subprocess.run(command, cwd=BASE, env=env, stdout=output, stderr=subprocess.STDOUT).returncode)


if __name__ == "__main__":
    main()
