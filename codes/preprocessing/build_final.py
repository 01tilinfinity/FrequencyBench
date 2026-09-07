"""Build the agreed top-half-priority sample; final folder contains only CSV/README.

python codes/preprocessing/build_final.py --write
python codes/preprocessing/build_final.py --check --offline
"""
import argparse
import csv
import gzip
import hashlib
import io
import json
import random
import re
import time
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/raw"
SOURCE = RAW / "wd_scan/timelines.before_overlapfix"
OUT = ROOT / "data/final"
LABEL_CACHE = RAW / "wikidata_label_cache.json"
UNIT_CACHE = RAW / "wikidata_statement_quantity_cache.json"
CLASSES = ["A-Day", "A-Few-Days", "A-Week", "A-Few-Weeks", "A-Month",
           "A-Few-Months", "A-Year", "A-Few-Years", "Many-Years"]
FIELDS = ["entity_id", "entity", "property_id", "property", "value_id", "value",
          "value_unit", "frequency", "frequency_days", "start_time", "end_time"]
SEED = 42
CAP = 100


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_cache(path, data):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def api(ids, props):
    for attempt in range(6):
        try:
            time.sleep(1.5)
            response = requests.get("https://www.wikidata.org/w/api.php",
                params={"action": "wbgetentities", "ids": "|".join(ids),
                        "props": props, "format": "json"},
                headers={"User-Agent": "FrequencyBench final dataset enrichment"}, timeout=30)
            if response.status_code == 429 and attempt < 5:
                retry = response.headers.get("Retry-After", "")
                delay = float(retry) if retry.isdigit() else min(60, 15 * (attempt + 1))
                print(f"Wikidata rate limit: retrying after {delay:g}s", flush=True)
                time.sleep(delay)
                continue
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                raise RuntimeError(data["error"])
            return data["entities"]
        except (requests.RequestException, ValueError, RuntimeError):
            if attempt == 5:
                raise
            time.sleep(2 ** attempt)


def make_sample():
    manifest = read_json(SOURCE.parent / "qlever_manifest.before_overlapfix.json")
    ranking = sorted((p for p in manifest if manifest[p].get("n_valid", 0) > 0),
                     key=lambda p: (-manifest[p]["n_valid"], int(p[1:])))
    top = set(ranking[:(len(ranking) + 1) // 2])
    assert len(ranking) == 379 and len(top) == 190
    pools = {c: [[], []] for c in CLASSES}
    digest = hashlib.sha256()
    for pid in sorted(ranking, key=lambda p: int(p[1:])):
        path = SOURCE / f"{pid}.jsonl"
        content = path.read_bytes()
        digest.update(path.name.encode() + b"\0" + content)
        seen, counts = set(), Counter()
        for line in content.splitlines():
            row = json.loads(line)
            qid, cls = row["subject"], row["frequency_class"]
            assert row["property"] == pid and qid not in seen
            seen.add(qid)
            counts[cls] += 1
            pools[cls][0 if pid in top else 1].append((pid, qid))
        assert counts == Counter(manifest[pid]["classes"])
    assert sum(len(p) for pools_c in pools.values() for p in pools_c) == 151547
    rng = random.Random(SEED)
    # Select all classes first; value draws/shuffling then use this same RNG.
    selected, selection_counts = [], {}
    # Compact key pools avoid retaining the full population's timeline arrays.
    needed = set()
    for cls in CLASSES:
        primary, secondary = pools[cls]
        keys = rng.sample(primary, min(CAP, len(primary)))
        keys += rng.sample(secondary, min(CAP - len(keys), len(secondary)))
        # Timeline-dependent value draws happen below, so selection is performed
        # for every class first and documented as such.
        selected.append((cls, keys))
        needed.update(keys)
        selection_counts[cls] = [len(primary), len(secondary),
                                sum(p in top for p, q in keys), sum(p not in top for p, q in keys)]
    chosen_rows = {}
    for pid in sorted({p for p, q in needed}, key=lambda p: int(p[1:])):
        with (SOURCE / f"{pid}.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                key = (pid, row["subject"])
                if key in needed:
                    chosen_rows[key] = row
    records = []
    for cls, keys in selected:
        bucket = []
        for key in keys:
            row = chosen_rows[key]
            value = rng.choice(row["timeline"])["value"]
            interval = min((s for s in row["timeline"] if s["value"] == value),
                           key=lambda s: s["start"])
            bucket.append({"qid": row["subject"], "pid": row["property"], "raw_value": value,
                           "frequency": cls, "days": row["median_interval_days"],
                           "start": interval["start"], "end": interval.get("end") or ""})
        rng.shuffle(bucket)
        records.extend(bucket)
    assert len(records) == 820
    assert len({(r["qid"], r["pid"]) for r in records}) == len(records)
    return records, ranking, selection_counts, digest.hexdigest(), manifest


def raw_value(text):
    if text.startswith("<"):
        return text.strip("<>").rsplit("/", 1)[-1]
    if text.startswith('"'):
        return text[1:].split('"')[0]
    return text


def resolve_units(records, types, offline):
    quantities = [r for r in records if types[r["pid"]] == "Quantity"]
    cache = read_json(UNIT_CACHE)
    wanted = defaultdict(list)
    for r in quantities:
        wanted[r["pid"]].append(r)
    for pid, candidates in wanted.items():
        matches = defaultdict(set)
        with gzip.open(SOURCE.parent / "qlever" / f"{pid}.tsv.gz", "rt", encoding="utf-8") as stream:
            for item in csv.DictReader(stream, delimiter="\t"):
                key = (raw_value(item["?i"]), raw_value(item["?v"]),
                       raw_value(item["?start"])[:10], raw_value(item["?end"])[:10])
                matches[key].add(raw_value(item["?st"]))
        for r in candidates:
            key = (r["qid"], r["raw_value"], r["start"], r["end"])
            r["statement_ids"] = sorted(matches[key])
            if not r["statement_ids"]:
                raise ValueError(f"No original quantity statement: {r}")
    missing = {sid for r in quantities for sid in r["statement_ids"] if sid not in cache}
    if missing and offline:
        raise ValueError("Quantity cache is incomplete")
    entity_ids = sorted({sid.split("-", 1)[0] for sid in missing})
    for offset in range(0, len(entity_ids), 10):
        entities = api(entity_ids[offset:offset + 10], "claims")
        for entity in entities.values():
            for claims in entity.get("claims", {}).values():
                for claim in claims:
                    sid = claim["id"].replace("$", "-")
                    if sid in missing:
                        value = claim["mainsnak"].get("datavalue", {}).get("value", {})
                        if not isinstance(value, dict) or "amount" not in value:
                            raise ValueError(f"Missing quantity metadata: {sid}")
                        cache[sid] = {"amount": value["amount"], "unit": value["unit"]}
        save_cache(UNIT_CACHE, cache)
        print(f"Quantity entities resolved: {min(offset + 10, len(entity_ids))}/{len(entity_ids)}", flush=True)
    for r in quantities:
        values = [cache[sid] for sid in r["statement_ids"]]
        assert all(Decimal(v["amount"]) == Decimal(r["raw_value"]) for v in values)
        units = {v["unit"] for v in values}
        if len(units) != 1:
            raise ValueError(f"Ambiguous quantity units: {r}")
        unit = units.pop()
        r["unit_id"] = unit.rsplit("/", 1)[-1] if unit != "1" else "1"


def resolve_labels(records, manifest, offline):
    cache = read_json(LABEL_CACHE)
    ids = {r["qid"] for r in records}
    ids |= {r["raw_value"] for r in records if re.fullmatch(r"Q\d+", r["raw_value"])}
    ids |= {r["unit_id"] for r in records if r.get("unit_id", "").startswith("Q")}
    pending = sorted(q for q in ids if not cache.get(q) or cache[q] == q)
    if pending and offline:
        raise ValueError(f"Label cache incomplete: {len(pending)} IDs")
    for offset in range(0, len(pending), 50):
        batch = pending[offset:offset + 50]
        entities = api(batch, "labels")
        for qid in batch:
            labels = entities.get(qid, {}).get("labels", {})
            priority = ["en", "mul", "ko"] + sorted(set(labels) - {"en", "mul", "ko"})
            cache[qid] = next((labels[l]["value"] for l in priority if labels.get(l)), qid)
        save_cache(LABEL_CACHE, cache)
        print(f"Labels resolved: {min(offset + 50, len(pending))}/{len(pending)}", flush=True)
    unresolved = [q for q in ids if not cache.get(q) or cache[q] == q]
    if unresolved:
        raise ValueError(f"Unresolved labels: {unresolved}")
    output = []
    for r in records:
        value_id = r["raw_value"] if re.fullmatch(r"Q\d+", r["raw_value"]) else ""
        unit_id = r.get("unit_id", "")
        output.append(dict(zip(FIELDS, [r["qid"], cache[r["qid"]], r["pid"], manifest[r["pid"]]["label"],
            value_id, cache[value_id] if value_id else r["raw_value"],
            "unitless" if unit_id == "1" else cache.get(unit_id, ""),
            r["frequency"], r["days"], r["start"], r["end"]])))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    records, ranking, counts, source_hash, manifest = make_sample()
    print("Sampling complete:", json.dumps(counts), flush=True)
    types = {p["pid"]: p["type"] for p in read_json(SOURCE.parent / "1_properties.json")}
    resolve_units(records, types, args.offline)
    rows = resolve_labels(records, manifest, args.offline)
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    payload = buffer.getvalue().encode("utf-8")
    csv_hash = hashlib.sha256(payload).hexdigest()
    path = OUT / "frequency_bench.csv"
    if args.check:
        assert path.read_bytes() == payload, "Final CSV does not match deterministic regeneration"
        print(f"Verified: {len(rows)} unique pairs, all labels/quantity units resolved; SHA256 {csv_hash}")
        return
    report = """# Frequency benchmark 최종 데이터

`frequency_bench.csv`: UTF-8 CSV, 820행. 샘플 단위는 entity–property 한 쌍이며 중복 쌍은 없습니다.

## 추출 규칙

- Plot 1과 동일한 `data/raw/wd_scan/timelines.before_overlapfix`의 151,547개 타임라인을 사용합니다.
- 유효 property 379개를 데이터 수 내림차순, 동률이면 PID 숫자 오름차순으로 정렬하고 상위 190개를 우선합니다. 누적 데이터 50%가 아니라 property 개수 50%(올림)입니다.
- 각 Frequency에서 우선 후보를 최대 100개 비복원 랜덤 추출하고, 부족할 때만 나머지 property의 같은 클래스에서 보충합니다. 전체 후보가 부족하면 전부 사용합니다.
- Python `random.Random(42)` 사용. 파일은 PID 숫자 오름차순, 행은 원본 순서로 후보를 구성합니다. 아래 클래스 순서대로 전체 클래스의 쌍을 먼저 `random.sample`로 선택합니다.
- 이어서 같은 RNG로 각 선택 타임라인의 이력 하나를 균등 선택하여 value를 정합니다. 따라서 서로 다른 value 자체의 균등 추출은 아닙니다. 같은 value의 가장 이른 start 이력을 택하며, 날짜 동률은 원본 첫 항목의 end를 유지합니다. 클래스별 결과를 같은 RNG로 shuffle합니다.
- property별 균등 할당은 하지 않습니다. 기존 라벨/필터/미래 날짜 정책을 변경하지 않습니다.

## 컬럼

| 컬럼 | 의미 |
|---|---|
| entity_id / entity | Entity QID / 자연어 라벨 |
| property_id / property | Property PID / 자연어 라벨 |
| value_id / value | Value QID / 자연어 라벨. 숫자·문자열·시간 리터럴은 value_id가 비고 value에 원래 값을 보존 |
| value_unit | Quantity의 단위 라벨. 명시적 무단위는 unitless, 비-Quantity는 빈칸 |
| frequency | 원본 Frequency 클래스 |
| frequency_days | 전체 entity–property 타임라인의 양수인 연속 start-to-start 간격 중앙값(일) |
| start_time / end_time | 선택된 value의 가장 이른 이력 한 건의 짝지어진 날짜. 종료일 누락은 빈칸 |

`end_time - start_time`은 `frequency_days`와 같을 필요가 없습니다. 날짜는 전체 타임라인의 양 끝이 아닙니다.
연·월 정밀도 날짜도 원본에서 YYYY-MM-DD로 정규화되어 있으므로 01-01/월초를 실제 일 단위 정밀도로 해석하면 안 됩니다.
동일 value의 반복 이력과 원본 timeline에 저장된 deprecated 항목은 추가 제거하지 않았습니다. Frequency 계산과 선택 이력의 모집단이 다를 수 있는 원본 특성을 유지합니다.
숫자의 단위는 원시 TSV statement ID를 Wikidata claim과 대조해 보강했습니다. 통화 환산은 하지 않으며 수치의 상·하한과 나머지 qualifier는 이 간결한 CSV에 싣지 않습니다.
라벨은 en → mul → ko → 기타 언어 순의 캐시를 사용합니다. 단위·라벨은 수집 당시 고정 스냅샷이 아닌 보강 조회값입니다. 원본의 사실 정확성이나 미래 예정값을 추가 검증/정정한 데이터는 아닙니다.

## 클래스별 후보와 최종 수

| Frequency | 상위 190 후보 | 나머지 후보 | 우선 추출 | 추가 추출 | 최종 |
|---|---:|---:|---:|---:|---:|
"""
    for cls in CLASSES:
        a, b, x, y = counts[cls]
        report += f"| {cls} | {a:,} | {b:,} | {x} | {y} | {x+y} |\n"
    report += "\n이번 실행은 모든 추가 추출이 0개입니다. A-Day는 전체 20개, 나머지 8개 클래스는 각각 100개입니다.\n"
    report += "\n## 우선 property 목록 (순위순)\n\n" + ", ".join(ranking[:190]) + "\n"
    report += f"\n## 재현 및 검증\n\n- 생성: `python codes/preprocessing/build_final.py --write`\n- 오프라인 재검증: `python codes/preprocessing/build_final.py --check --offline`\n- 보강 캐시: `data/raw/wikidata_label_cache.json`, `data/raw/wikidata_statement_quantity_cache.json`\n- 원본 파일명+내용 결합 SHA256: `{source_hash}`\n- 최종 CSV SHA256: `{csv_hash}`\n"
    OUT.mkdir(parents=True, exist_ok=True)
    for dest, content in [(path, payload), (OUT / "README.md", report.encode("utf-8"))]:
        if dest.exists() and dest.read_bytes() != content:
            raise FileExistsError(f"Refusing to overwrite different existing output: {dest}")
    path.write_bytes(payload)
    (OUT / "README.md").write_text(report, encoding="utf-8")
    print(f"Saved {path}: {len(rows)} rows, {len(FIELDS)} columns; SHA256 {csv_hash}")


if __name__ == "__main__":
    main()
