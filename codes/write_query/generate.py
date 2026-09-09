"""Generate questions with GPT-5.6 Luna and update the input CSV in place."""

import argparse
import csv
import hashlib
import io
import json
import os
import stat
import tempfile
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROMPT = Path(__file__).resolve().parent / "prompt" / "query.txt"


def parse_args():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/final/frequency_bench.csv")
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, help="Maximum number of new queries to generate.")
    parser.add_argument("--resume", action="store_true", help="Keep existing queries and fill empty cells.")
    parser.add_argument("--dry-run", action="store_true", help="Preview a request without API calls or file changes.")
    args = parser.parse_args()
    for name in ("max_tokens", "timeout", "workers", "limit"):
        value = getattr(args, name)
        if value is not None and value <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.max_retries < 0:
        parser.error("--max-retries must be nonnegative")
    if args.input.resolve() == args.prompt.resolve():
        parser.error("Input CSV and prompt must be different files")
    return args


def load_input(path):
    raw = path.read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    fields = reader.fieldnames
    if not fields or not {"entity", "property"}.issubset(fields):
        raise ValueError("Input CSV must have entity and property columns")
    if len(fields) != len(set(fields)):
        raise ValueError("Input columns must be unique")
    rows = list(reader)
    for index, row in enumerate(rows, 1):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Invalid CSV column count at data row {index}")
        if not row["entity"].strip() or not row["property"].strip():
            raise ValueError(f"Empty entity/property at data row {index}")
    return fields, rows, hashlib.sha256(raw).digest()


def pending_indices(rows, resume):
    pending = [i for i, row in enumerate(rows) if not row.get("query", "").strip()]
    if len(pending) != len(rows) and not resume:
        raise ValueError("Existing queries found; use --resume to fill only empty query cells")
    return pending


def save_csv(path, fields, rows, expected_digest):
    """Replace the CSV atomically; refuse to overwrite concurrent edits."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    raw = output.getvalue().encode("utf-8")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as f:
            temp_path = Path(f.name)
            os.fchmod(f.fileno(), stat.S_IMODE(path.stat().st_mode))
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        if hashlib.sha256(path.read_bytes()).digest() != expected_digest:
            raise ValueError("Input CSV changed during generation; stopped to preserve external edits")
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return hashlib.sha256(raw).digest()


def build_messages(prompt, row):
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(
            {"entity": row["entity"], "relation": row["property"]}, ensure_ascii=False
        )},
    ]


def generate_query(client, args, messages):
    response = client.chat.completions.create(
        model=args.model,
        messages=messages,
        reasoning_effort="none",
        max_completion_tokens=args.max_tokens,
    )
    if not response.choices:
        raise ValueError("Model returned no choices")
    choice = response.choices[0]
    if choice.finish_reason != "stop":
        raise ValueError(f"Model did not finish normally: {choice.finish_reason}")
    query = (choice.message.content or "").strip()
    if not query or "\n" in query or "\r" in query or not query.endswith("?"):
        raise ValueError("Model must return a nonempty question on one line ending with ?")
    return query


def fill_queries(client, args, prompt, fields, rows, digest, pending):
    fields = fields if "query" in fields else fields + ["query"]
    completed = len(rows) - len(pending)
    selected = pending if args.limit is None else pending[:args.limit]
    indices = iter(selected)
    saved = 0
    pool = ThreadPoolExecutor(max_workers=args.workers)
    futures = {}

    def submit_next():
        index = next(indices, None)
        if index is not None:
            future = pool.submit(generate_query, client, args, build_messages(prompt, rows[index]))
            futures[future] = index

    try:
        for _ in range(min(args.workers, len(selected))):
            submit_next()
        with tqdm(total=len(rows), initial=completed, desc="Generating queries", unit="query", dynamic_ncols=True, mininterval=1) as progress:
            while futures:
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in done:
                    index = futures.pop(future)
                    try:
                        query = future.result()
                    except Exception as exc:
                        # Provider error messages can contain secrets or request bodies.
                        raise ValueError(
                            f"Generation failed at data row {index + 1} ({type(exc).__name__}, "
                            f"status={getattr(exc, 'status_code', 'n/a')}). "
                            "Saved queries are preserved; retry with --resume."
                        ) from None
                    rows[index]["query"] = query
                    digest = save_csv(args.input, fields, rows, digest)
                    saved += 1
                    progress.update(1)
                for _ in done:
                    submit_next()
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    return saved


def main():
    args = parse_args()
    try:
        prompt = args.prompt.read_text(encoding="utf-8").strip()
        if not prompt:
            raise ValueError(f"Write your prompt in {args.prompt} before running")
        fields, rows, digest = load_input(args.input)
        pending = pending_indices(rows, args.resume)
        if not pending:
            print("No pending rows.")
            return
        if args.dry_run:
            print(json.dumps({
                "model": args.model,
                "input": str(args.input),
                "update_in_place": True,
                "reasoning_effort": "none",
                "pending_rows": len(pending),
                "selected_rows": min(len(pending), args.limit) if args.limit else len(pending),
                "messages": build_messages(prompt, rows[pending[0]]),
            }, ensure_ascii=False, indent=2))
            return
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise ValueError("OPENAI_API_KEY not set in environment or project .env")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ValueError("Install dependencies: pip install -r codes/write_query/requirements.txt") from exc
        with OpenAI(api_key=key, base_url="https://api.openai.com/v1", timeout=args.timeout, max_retries=args.max_retries) as client:
            saved = fill_queries(client, args, prompt, fields, rows, digest, pending)
        print(f"Saved {saved} queries in place: {args.input}")
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
    except KeyboardInterrupt:
        raise SystemExit("Interrupted. Saved queries are preserved; retry with --resume.") from None


if __name__ == "__main__":
    main()
