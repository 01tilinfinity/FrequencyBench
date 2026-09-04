"""
Stage 3: Wikidata temporal statement 수집 (SPARQL)
- 2_temporal_properties.json의 1,141개 property 전수
- 쿼리는 실측상 유일하게 통과한 pq: 형태 (pqv:는 504)
- 규모가 작은 property부터 순회, class 9개 모두 100 도달 시 early stop
- raw statement와 계산된 timeline을 모두 저장
- 매 property마다 체크포인트, 중단 후 재실행 시 이어서 진행
"""
import requests, time, json, os, statistics, sys, csv
from collections import defaultdict
from datetime import date
from pathlib import Path
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from common.config import RAW, UA
    OUT = str(RAW / "wd_scan"); H = UA
except Exception:
    OUT = "../../data/raw/wd_scan"
    H = {"User-Agent": "FrequencyBench/0.1 (hs01151116@korea.ac.kr)"}

EP = "https://query.wikidata.org/sparql"
DDIR = f"{OUT}/data"          # raw statements
TDIR = f"{OUT}/timelines"     # 계산된 timeline + frequency
os.makedirs(DDIR, exist_ok=True)
os.makedirs(TDIR, exist_ok=True)

TIMEOUT = 70                  # 서버가 59초까지 쓰는 것을 실측함
PAGE = 10000
MAX_PER_PROP = 50_000
TARGET_PER_CLASS = 100
MIN_INTERVALS = 2             # statement >= 3

CLASSES = [("A-Day", 2), ("A-Few-Days", 7), ("A-Week", 14),
           ("A-Few-Weeks", 30), ("A-Month", 60), ("A-Few-Months", 365),
           ("A-Year", 730), ("A-Few-Years", 3650), ("Many-Years", 10**9)]
CLASS_NAMES = [c for c, _ in CLASSES]
PREC_MIN = {9: 300, 10: 25, 11: 0}

Q = """
SELECT ?i ?v ?start ?end ?rank WHERE {{
  ?i p:{p} ?st .
  ?st ps:{p} ?v ; pq:P580 ?start ; wikibase:rank ?rank .
  OPTIONAL {{ ?st pq:P582 ?end }}
}}
LIMIT {lim} OFFSET {off}
"""

SIZE_Q = """
SELECT (COUNT(*) AS ?n) WHERE {{
  {{ SELECT ?st WHERE {{ ?i p:{p} ?st . ?st pq:P580 ?t }} LIMIT 20000 }}
}}
"""


def query(q, timeout=TIMEOUT):
    try:
        r = requests.get(EP, params={"query": q, "format": "json"},
                         headers=H, timeout=timeout)
        if r.status_code == 200:
            return "ok", r.json()
        if r.status_code in (429, 503):
            time.sleep(20); return "retry", None
        return "timeout", None
    except requests.exceptions.Timeout:
        return "timeout", None
    except Exception:
        return "error", None


# ------------------------------------------------------------- parsing
def infer_prec(s):
    """pqv를 못 쓰므로 '2016-00-00' 패턴에서 precision 추론"""
    if s[5:7] == "00": return 9
    if s[8:10] == "00": return 10
    return 11


def parse(x, pid):
    sv = x["start"]["value"]
    if sv.startswith("-"):            # BC 연도 제외
        return None
    st = sv[:10]
    ev = x.get("end", {}).get("value", "")
    en = ev[:10] if ev and not ev.startswith("-") else None
    v = x["v"]["value"]
    return {"subject": x["i"]["value"].split("/")[-1], "property": pid,
            "value": v.split("/")[-1] if "/entity/" in v else v,
            "start": st, "start_prec": infer_prec(st),
            "end": en, "end_prec": infer_prec(en) if en else None,
            "rank": x["rank"]["value"].split("#")[-1]}


def to_date(s, prec):
    y, m, d = int(s[:4]), int(s[5:7]), int(s[8:10])
    if prec <= 9:    m, d = 1, 1
    elif prec == 10: d = 1
    return date(max(y, 1), max(m, 1), max(d, 1))


def evaluate(stmts):
    """timeline 하나 → (class or None, 사유, detail)"""
    stmts = [s for s in stmts if s["rank"] != "DeprecatedRank" and s["start"]]
    if len(stmts) < MIN_INTERVALS + 1:
        return None, "too_few", {}
    if len({s["value"] for s in stmts}) < 2:
        return None, "single_value", {}
    try:
        rows = [(to_date(s["start"], s["start_prec"]),
                 to_date(s["end"], s["end_prec"]) if s["end"] else date(9999, 12, 31),
                 s["start_prec"]) for s in stmts]
    except ValueError:
        return None, "bad_date", {}
    rows.sort()

    for i in range(len(rows) - 1):                # 구간 겹침 = 누적형
        if rows[i][1] > rows[i + 1][0]:
            return None, "overlap", {}

    prec = min(r[2] for r in rows)
    if all(s["start"][5:] == "01-01" for s in stmts):
        prec = min(prec, 9)                        # 실질 year precision

    iv = [(rows[i + 1][0] - rows[i][0]).days for i in range(len(rows) - 1)]
    iv = [d for d in iv if d > 0]
    if len(iv) < MIN_INTERVALS:
        return None, "zero_interval", {}

    med = statistics.median(iv)
    if med < PREC_MIN.get(prec, 0):
        return None, "precision", {}

    detail = {"median_interval_days": med, "intervals": iv,
              "n_intervals": len(iv), "min_precision": prec,
              "n_statements": len(stmts),
              "first_start": rows[0][0].isoformat(),
              "last_start": rows[-1][0].isoformat()}
    for name, ub in CLASSES:
        if med < ub:
            return name, "ok", detail
    return None, "unbinned", {}


def count_property(pid):
    """raw를 읽어 timeline 계산 → timelines/{pid}.jsonl 저장"""
    fp = f"{DDIR}/{pid}.jsonl"
    groups = defaultdict(list)
    if os.path.exists(fp):
        with open(fp, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                groups[r["subject"]].append(r)

    cnt = {c: 0 for c in CLASS_NAMES}
    reasons = defaultdict(int)
    valid_rows = []

    for subj, stmts in groups.items():
        cls, why, detail = evaluate(stmts)
        if cls:
            cnt[cls] += 1
            valid_rows.append({
                "subject": subj, "property": pid,
                "frequency_class": cls, **detail,
                "timeline": sorted(
                    [{"value": s["value"], "start": s["start"],
                      "end": s["end"], "prec": s["start_prec"]} for s in stmts],
                    key=lambda r: r["start"])})
        else:
            reasons[why] += 1

    tp = f"{TDIR}/{pid}.jsonl"
    if valid_rows:
        with open(tp, "w", encoding="utf-8") as f:
            for r in valid_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    elif os.path.exists(tp):
        os.remove(tp)

    return cnt, dict(reasons), len(groups)


# ------------------------------------------------------------- harvest
def harvest(pid):
    fp = f"{DDIR}/{pid}.jsonl"
    if os.path.exists(fp):
        os.remove(fp)
    n, off, page, fails = 0, 0, PAGE, 0
    while n < MAX_PER_PROP:
        status, data = query(Q.format(p=pid, lim=page, off=off))
        if status == "retry":
            fails += 1
            if fails > 5: break
            continue
        if status != "ok":
            if page > 1000:
                page //= 2; continue
            break
        b = data["results"]["bindings"]
        if b:
            with open(fp, "a", encoding="utf-8") as f:
                for x in b:
                    r = parse(x, pid)
                    if r:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += len(b); off += len(b)
        if len(b) < page:
            break
        time.sleep(0.3)
    return n


def get_order(props):
    """규모를 재서 작은 property부터 정렬 (캐시)"""
    path = f"{OUT}/3_sizes.json"
    sizes = json.load(open(path)) if os.path.exists(path) else {}
    todo = [p for p in props if p not in sizes]
    if todo:
        print(f"[size] measuring {len(todo)} properties")
        try:
            for i, p in enumerate(tqdm(todo, unit="p", desc="size")):
                status, data = query(SIZE_Q.format(p=p), timeout=45)
                sizes[p] = (int(data["results"]["bindings"][0]["n"]["value"])
                            if status == "ok" else 10**9)
                if i % 10 == 0:
                    json.dump(sizes, open(path, "w"))
        except KeyboardInterrupt:
            json.dump(sizes, open(path, "w"))
            print(f"\n[size] interrupted, saved {len(sizes)}")
            raise
        json.dump(sizes, open(path, "w"))
    return sorted([p for p in props if p in sizes], key=lambda p: sizes[p])


# ------------------------------------------------------------- report
def report(log):
    tot = {c: 0 for c in CLASS_NAMES}
    for v in log.values():
        for c in CLASS_NAMES:
            tot[c] += v["classes"][c]

    print("\n=== class distribution ===")
    for c in CLASS_NAMES:
        mark = "OK " if tot[c] >= TARGET_PER_CLASS else "   "
        print(f"  {mark}{c:<16}{tot[c]:>7}  {'#' * min(50, tot[c] // 10)}")

    rows = sorted(({"pid": k, **v} for k, v in log.items()),
                  key=lambda r: -r["n_valid"])
    with open(f"{OUT}/3_scan_report.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pid", "label", "n_stmt", "n_groups", "n_valid"] + CLASS_NAMES)
        for r in rows:
            w.writerow([r["pid"], r["label"], r["n_stmt"], r["n_groups"],
                        r["n_valid"]] + [r["classes"][c] for c in CLASS_NAMES])

    print(f"\nwrote {OUT}/3_scan_report.csv")
    print(f"properties with >=1 valid timeline: "
          f"{sum(1 for r in rows if r['n_valid'] > 0)} / {len(rows)}")
    short = [c for c in CLASS_NAMES if tot[c] < TARGET_PER_CLASS]
    if short:
        print(f"부족: {', '.join(short)}")


def main():
    meta = json.load(open(f"{OUT}/2_temporal_properties.json"))
    order = get_order(list(meta.keys()))

    logp = f"{OUT}/3_scan_log.json"
    log = json.load(open(logp)) if os.path.exists(logp) else {}
    todo = [p for p in order if p not in log]
    print(f"\n[harvest] {len(log)} done, {len(todo)} to go (of {len(order)})\n")

    def totals():
        t = {c: 0 for c in CLASS_NAMES}
        for v in log.values():
            for c in CLASS_NAMES:
                t[c] += v["classes"][c]
        return t

    def flush():
        json.dump(log, open(logp, "w"), ensure_ascii=False)
        json.dump(totals(), open(f"{OUT}/3_class_counts.json", "w"), indent=1)

    pbar = tqdm(todo, unit="p", desc="harvest")
    try:
        for pid in pbar:
            n = harvest(pid)
            cnt, reasons, ngroups = count_property(pid)
            valid = sum(cnt.values())
            log[pid] = {"label": meta[pid]["label"], "n_stmt": n,
                        "n_groups": ngroups, "n_valid": valid,
                        "classes": cnt, "reasons": reasons}
            flush()

            tot = totals()
            filled = [c for c in CLASS_NAMES if tot[c] >= TARGET_PER_CLASS]
            pbar.set_postfix(pid=pid, valid=valid, filled=f"{len(filled)}/9")
            if valid > 0:
                pbar.write(f"{pid:<9}{meta[pid]['label'][:24]:<26} stmt={n:<6} "
                           f"valid={valid:<5} | "
                           + " ".join(f"{k[2:]}={v}" for k, v in cnt.items() if v))
            if len(filled) == len(CLASS_NAMES):
                pbar.write(f"\n*** all 9 classes filled — stop at {pid} ***")
                break
    except KeyboardInterrupt:
        pbar.write("\n[interrupted]")
    finally:
        flush()
        report(log)


if __name__ == "__main__":
    main()