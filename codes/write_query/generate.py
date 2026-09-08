import argparse
import csv
import json
import os
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROMPT = Path(__file__).resolve().parent / "prompt" / "query.txt"


def parse_args():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/final/frequency_bench.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "data/final/frequency_bench_queries.csv")
    parser.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument("--model", default=os.getenv("GLM_MODEL", "glm-4.7"))
    parser.add_argument("--base-url", default=os.getenv("GLM_BASE_URL", "https://api.z.ai/api/paas/v4/"))
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--limit", type=int, help="Maximum number of new queries to generate.")
    parser.add_argument("--resume", action="store_true", help="Continue from an existing output CSV.")
    parser.add_argument("--dry-run", action="store_true", help="Print the first pending request without calling GLM.")
    args = parser.parse_args()
    for name in ("max_tokens", "timeout", "limit"):
        value = getattr(args, name)
        if value is not None and value <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.max_retries < 0:
        parser.error("--max-retries must be nonnegative")
    if not 0 <= args.temperature <= 1:
        parser.error("--temperature must be between 0 and 1")
    if args.input.resolve() == args.output.resolve():
        parser.error("Input and output must be different files")
    if args.prompt.resolve() == args.output.resolve():
        parser.error("Prompt and output must be different files")
    return args


def load_input(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        if not fields or not {"entity", "property"}.issubset(fields):
            raise ValueError("Input CSV must have entity and property columns")
        if len(fields) != len(set(fields)) or "query" in fields:
            raise ValueError("Input columns must be unique and must not include query")
        rows = list(reader)
    for index, row in enumerate(rows, 1):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Invalid CSV column count at data row {index}")
        if not row["entity"].strip() or not row["property"].strip():
            raise ValueError(f"Empty entity/property at data row {index}")
    return fields, rows


def completed_count(path, fields, rows, resume):
    if not path.exists():
        return 0
    if not resume:
        raise ValueError(f"Output already exists: {path}. Use --resume or another --output.")
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != fields + ["query"]:
            raise ValueError("Existing output has incompatible columns")
        count = 0
        for index, row in enumerate(reader):
            if (
                index >= len(rows)
                or None in row
                or {field: row.get(field) for field in fields} != rows[index]
                or not (row.get("query") or "").strip()
            ):
                raise ValueError(f"Existing output does not match input or is incomplete at data row {index + 1}")
            count += 1
    return count


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
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        extra_body={"thinking": {"type": "disabled"}},
    )
    if not response.choices:
        raise ValueError("GLM returned no choices")
    choice = response.choices[0]
    if choice.finish_reason != "stop":
        raise ValueError(f"GLM did not finish normally: {choice.finish_reason}")
    query = (choice.message.content or "").strip()
    if not query:
        raise ValueError("GLM returned an empty query")
    return query


def main():
    args = parse_args()
    try:
        prompt = args.prompt.read_text(encoding="utf-8").strip()
        if not prompt:
            raise ValueError(f"Write your prompt in {args.prompt} before running")
        fields, rows = load_input(args.input)
        start = completed_count(args.output, fields, rows, args.resume)
        stop = len(rows) if args.limit is None else min(len(rows), start + args.limit)
        if start == stop:
            print("No pending rows.")
            return
        if args.dry_run:
            print(json.dumps({
                "model": args.model,
                "base_url": args.base_url,
                "pending_rows": stop - start,
                "messages": build_messages(prompt, rows[start]),
            }, ensure_ascii=False, indent=2))
            return
        key = os.getenv("GLM_API_KEY")
        if not key:
            raise ValueError("GLM_API_KEY not set in environment or project .env")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ValueError("Install dependencies: pip install -r codes/write_query/requirements.txt") from exc
        args.output.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if args.resume and args.output.exists() else "x"
        with OpenAI(
            api_key=key, base_url=args.base_url,
            timeout=args.timeout, max_retries=args.max_retries,
        ) as client, args.output.open(mode, newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields + ["query"])
            if mode == "x":
                writer.writeheader()
                f.flush()
            for index in range(start, stop):
                try:
                    query = generate_query(client, args, build_messages(prompt, rows[index]))
                except Exception as exc:
                    # Do not print provider response bodies, which can contain sensitive data.
                    raise ValueError(
                        f"Generation failed at data row {index + 1} ({type(exc).__name__}, "
                        f"status={getattr(exc, 'status_code', 'n/a')}). "
                        "Completed rows are saved; retry with --resume."
                    ) from exc
                writer.writerow({**rows[index], "query": query})
                f.flush()
                print(f"[{index + 1}/{len(rows)}] saved", flush=True)
        print(f"Saved {stop - start} queries to {args.output}")
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
    except KeyboardInterrupt:
        raise SystemExit("Interrupted. Completed rows are saved; retry with --resume.") from None


if __name__ == "__main__":
    main()
