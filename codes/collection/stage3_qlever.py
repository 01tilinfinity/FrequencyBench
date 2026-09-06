"""
Stage 3 (QLever): Wikidata temporal statement 전수 수집
- 2_temporal_properties.json의 1,141개 property 전수, 상한/early stop 없음
- QLever endpoint는 Wikidata와 준실시간 동기화 (2026-09-04 확인)
- pqv: 사용 → precision 정확히 확보 (WDQS에서는 504)
- statement ID 저장 → 중복 제거·검증
- .part로 스트리밍 수신 → COUNT 대조 후 gzip 확정
- raw statement와 계산된 timeline 모두 저장, property마다 체크포인트
"""
import requests, time, json, os, gzip, csv, sys, statistics
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from common.config import RAW, UA
    OUT = str(RAW / "wd_scan"); CONTACT = UA["User-Agent"]
except Exception:
    OUT = "../../data/raw/wd_scan"
    CONTACT = "FrequencyBench/0.1 (hs01151116@korea.ac.kr)"

EP = "https://qlever.dev/api/wikidata"
H = {"Accept": "text/tab-separated-values", "User-Agent": CONTACT}

DDIR = f"{OUT}/qlever"        # raw TSV (gzip)
TDIR = f"{OUT}/timelines"     # 계산된 timeline
for d in (DDIR, TDIR):
    os.makedirs(d, exist_ok=True)

TIMEOUT = 1800                # 큰 property는 오래 걸림
RETRIES = 3
MIN_ROWS_RATIO = 0.95         # COUNT 대비 이 비율 미만이면 재시도
MIN_INTERVALS = 2             # statement >= 3

CLASSES = [("A-Day", 2), ("A-Few-Days", 7), ("A-Week", 14),
           ("A-Few-Weeks", 30), ("A-Month", 60), ("A-Few-Months", 365),
           ("A-Year", 730), ("A-Few-Years", 3650), ("Many-Years", 10**9)]
CLASS_NAMES = [c for c, _ in CLASSES]
PREC_MIN = {9: 300, 10: 25, 11: 0}

PREFIX = """PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX schema: <http://schema.org/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX pqv: <http://www.wikidata.org/prop/qualifier/value/>
"""

Q = PREFIX + """
SELECT ?st ?i ?v ?start ?sprec ?end ?eprec ?rank WHERE {{
  ?i p:{p} ?st .
  ?st ps:{p} ?v ; wikibase:rank ?rank .
  ?st pqv:P580 ?sn .
  ?sn wikibase:timeValue ?start ; wikibase:timePrecision ?sprec .
  OPTIONAL {{ ?st pqv:P582 ?en .
             ?en wikibase:timeValue ?end ; wikibase:timePrecision ?eprec . }}
}}
"""

COUNT_Q = PREFIX + """
SELECT (COUNT(*) AS ?n) WHERE {{
  ?i p:{p} ?st .
  ?st ps:{p} ?v .
  ?st pqv:P580 ?sn .
}}
"""

SNAPSHOT_Q = PREFIX + """
SELECT (MAX(?d) AS ?latest) WHERE {{ ?s schema:dateModified ?d }}
"""


# ------------------------------------------------------------- fetch
def tsv_scalar(text):
    """헤더 1줄 + 값 1줄 TSV → 문자열 값"""
    lines = text.strip().split("\n")
    if len(lines) < 2:
        return None
    v = lines[1].strip()
    if v.startswith('"'):
        v = v[1:].split('"')[0]
    return v.split("^^")[0]


def snapshot_info():
    """수집 시점의 인덱스 최신성 기록 (논문 재현성용)"""
    try:
        r = requests.get(EP, params={"query": SNAPSHOT_Q}, headers=H, timeout=300)
        return tsv_scalar(r.text) if r.status_code == 200 else None
    except Exception:
        return None


def expected_count(pid):
    try:
        r = requests.get(EP, params={"query": COUNT_Q.format(p=pid)},
                         headers=H, timeout=900)
        if r.status_code != 200:
            return None
        v = tsv_scalar(r.text)
        return int(v) if v is not None else None
    except Exception:
        return None


def fetch(pid, tmp):
    """스트리밍으로 .part 저장 → (행수, 바이트)"""
    with requests.get(EP, params={"query": Q.format(p=pid)},
                      headers=H, timeout=TIMEOUT, stream=True) as r:
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        nb = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk); nb += len(chunk)
    with open(tmp, "rb") as f:
        nrows = sum(1 for _ in f) - 1        # 헤더 제외
    return max(nrows, 0), nb


# ------------------------------------------------------------- parsing
def qid(uri):
    u = uri.strip()
    if u.startswith("<"):
        return u.strip("<>").split("/")[-1]
    if u.startswith('"'):
        return u[1:].split('"')[0]
    return u


def clean_time(s):
    """'"2015-10-02T00:00:00Z"^^<...>' → '2015-10-02', BC는 None"""
    s = s.strip()
    if not s:
        return None
    if s.startswith('"'):
        s = s[1:].split('"')[0]
    if s.startswith("-"):
        return None
    return s[:10] if len(s) >= 10 else None


def clean_int(s):
    s = s.strip()
    if not s:
        return None
    if s.startswith('"'):
        s = s[1:].split('"')[0]
    try:
        return int(s.split("^^")[0])
    except ValueError:
        return None


def read_rows(pid):
    """gzip TSV → dict 제너레이터 (statement ID로 중복 제거)"""
    fp = f"{DDIR}/{pid}.tsv.gz"
    if not os.path.exists(fp):
        return
    seen = set()
    with gzip.open(fp, "rt", encoding="utf-8") as f:
        next(f, None)                        # 헤더
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 8:
                continue
            sid = c[0]
            if sid in seen:
                continue
            seen.add(sid)
            st = clean_time(c[3])
            if not st:
                continue
            sp = clean_int(c[4])
            yield {"subject": qid(c[1]), "property": pid, "value": qid(c[2]),
                   "start": st, "start_prec": sp if sp is not None else 11,
                   "end": clean_time(c[5]), "end_prec": clean_int(c[6]),
                   "rank": c[7].strip().strip("<>").split("#")[-1]}


# ------------------------------------------------------------- analysis
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
    # try:
    #     rows = [(to_date(s["start"], s["start_prec"]),
    #              to_date(s["end"], s["end_prec"] or 11) if s["end"]
    #              else date(9999, 12, 31),
    #              s["start_prec"]) for s in stmts]
    # except ValueError:
    #     return None, "bad_date", {}
    # rows.sort()

    # for i in range(len(rows) - 1):            # 구간 겹침 = 누적형
    #     if rows[i][1] > rows[i + 1][0]:
    #         return None, "overlap", {}

    try:
        rows = [(to_date(s["start"], s["start_prec"]),
                to_date(s["end"], s["end_prec"] or 11) if s["end"] else None,
                s["start_prec"]) for s in stmts]

    except ValueError:
        return None, "bad_date", {}

    rows.sort(key=lambda r: r[0])

    for i in range(len(rows) - 1):            # end가 있을 때만 겹침 판정
        if rows[i][1] is not None and rows[i][1] > rows[i + 1][0]:
            return None, "overlap", {}

    prec = min(r[2] for r in rows)
    if all(s["start"][5:] == "01-01" for s in stmts):
        prec = min(prec, 9)                   # 실질 year precision

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


def analyze(pid):
    """raw를 읽어 timeline 계산 → timelines/{pid}.jsonl 저장"""
    groups = defaultdict(list)
    for r in read_rows(pid):
        groups[r["subject"]].append(r)

    cnt = {c: 0 for c in CLASS_NAMES}
    reasons = defaultdict(int)
    valid = []
    for subj, stmts in groups.items():
        cls, why, detail = evaluate(stmts)
        if cls:
            cnt[cls] += 1
            valid.append({"subject": subj, "property": pid,
                          "frequency_class": cls, **detail,
                          "timeline": sorted(
                              [{"value": s["value"], "start": s["start"],
                                "end": s["end"], "prec": s["start_prec"]}
                               for s in stmts], key=lambda r: r["start"])})
        else:
            reasons[why] += 1

    tp = f"{TDIR}/{pid}.jsonl"
    if valid:
        with open(tp, "w", encoding="utf-8") as f:
            for r in valid:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    elif os.path.exists(tp):
        os.remove(tp)
    return cnt, dict(reasons), len(groups)


# ------------------------------------------------------------- report
def report(man):
    tot = {c: 0 for c in CLASS_NAMES}
    for v in man.values():
        for c in CLASS_NAMES:
            tot[c] += v.get("classes", {}).get(c, 0)

    print("\n=== class distribution (full scan) ===")
    for c in CLASS_NAMES:
        print(f"  {c:<16}{tot[c]:>9}  {'#' * min(50, tot[c] // 200)}")

    rows = sorted(({"pid": k, **v} for k, v in man.items()),
                  key=lambda r: -r.get("n_valid", 0))
    with open(f"{OUT}/qlever_report.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pid", "label", "rows", "expected", "n_groups",
                    "n_valid", "sec", "status"] + CLASS_NAMES)
        for r in rows:
            w.writerow([r["pid"], r.get("label", ""), r.get("rows", 0),
                        r.get("expected", ""), r.get("n_groups", ""),
                        r.get("n_valid", 0), r.get("sec", ""), r.get("status")]
                       + [r.get("classes", {}).get(c, 0) for c in CLASS_NAMES])

    bad = [k for k, v in man.items() if v.get("status") != "ok"]
    size = sum(os.path.getsize(f"{DDIR}/{f}") for f in os.listdir(DDIR)
               if f.endswith(".tsv.gz"))
    print(f"\ntotal rows: {sum(r.get('rows', 0) for r in rows):,}")
    print(f"properties with >=1 valid timeline: "
          f"{sum(1 for r in rows if r.get('n_valid', 0) > 0)} / {len(rows)}")
    print(f"compressed: {size / 1e9:.2f} GB   failed: {len(bad)}")
    if bad:
        print("failed:", ", ".join(bad[:20]))
    print(f"wrote {OUT}/qlever_report.csv")


# ------------------------------------------------------------- main
def main():
    meta = json.load(open(f"{OUT}/2_temporal_properties.json"))

    # 이전 WDQS 규모 측정이 있으면 작은 것부터, 없으면 P번호순
    spath = f"{OUT}/3_sizes.json"
    sizes = json.load(open(spath)) if os.path.exists(spath) else {}
    order = sorted(meta.keys(), key=lambda p: (sizes.get(p, 10**9), int(p[1:])))

    mpath = f"{OUT}/qlever_manifest.json"
    man = json.load(open(mpath)) if os.path.exists(mpath) else {}
    todo = [p for p in order if man.get(p, {}).get("status") != "ok"]

    # 수집 메타데이터 (재현성)
    ipath = f"{OUT}/qlever_run_info.json"
    if not os.path.exists(ipath):
        info = {"endpoint": EP,
                "started_at": datetime.utcnow().isoformat() + "Z",
                "index_latest_modification": snapshot_info(),
                "n_properties": len(order)}
        json.dump(info, open(ipath, "w"), indent=1)
        print(f"endpoint index latest modification: "
              f"{info['index_latest_modification']}")

    print(f"{len(order) - len(todo)} done, {len(todo)} to go (of {len(order)})\n")

    def totals():
        t = {c: 0 for c in CLASS_NAMES}
        for v in man.values():
            for c in CLASS_NAMES:
                t[c] += v.get("classes", {}).get(c, 0)
        return t

    pbar = tqdm(todo, unit="p")
    try:
        for pid in pbar:
            out, tmp = f"{DDIR}/{pid}.tsv.gz", f"{DDIR}/{pid}.part"
            ok = False
            for attempt in range(RETRIES):
                try:
                    t0 = time.time()
                    rows, nb = fetch(pid, tmp)
                    el = time.time() - t0

                    exp = expected_count(pid)
                    if exp is not None and exp > 0 and rows < exp * MIN_ROWS_RATIO:
                        raise RuntimeError(f"rows {rows} < expected {exp}")

                    with open(tmp, "rb") as fi, gzip.open(out, "wb", 6) as fo:
                        while True:
                            c = fi.read(1 << 20)
                            if not c:
                                break
                            fo.write(c)
                    os.remove(tmp)

                    cnt, reasons, ngroups = analyze(pid)
                    man[pid] = {"label": meta[pid]["label"], "rows": rows,
                                "expected": exp, "bytes": nb, "sec": round(el, 1),
                                "n_groups": ngroups, "n_valid": sum(cnt.values()),
                                "classes": cnt, "reasons": reasons, "status": "ok"}
                    ok = True
                    break
                except Exception as e:
                    if attempt == RETRIES - 1:
                        man[pid] = {"label": meta[pid]["label"], "rows": 0,
                                    "classes": {c: 0 for c in CLASS_NAMES},
                                    "status": "fail", "error": str(e)[:200]}
                    else:
                        time.sleep(15 * (attempt + 1))
                finally:
                    if os.path.exists(tmp) and not ok:
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass

            json.dump(man, open(mpath, "w"), ensure_ascii=False)
            json.dump(totals(), open(f"{OUT}/3_class_counts.json", "w"), indent=1)

            v = man[pid]
            pbar.set_postfix(pid=pid, rows=v.get("rows", 0),
                             valid=v.get("n_valid", 0))
            if v.get("n_valid", 0) > 0:
                pbar.write(f"{pid:<9}{meta[pid]['label'][:24]:<26} "
                           f"rows={v['rows']:<7} valid={v['n_valid']:<6} | "
                           + " ".join(f"{k[2:]}={n}"
                                      for k, n in v["classes"].items() if n))
            elif v.get("status") == "fail":
                pbar.write(f"{pid:<9}FAIL  {v.get('error', '')[:80]}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pbar.write("\n[interrupted]")
    finally:
        json.dump(man, open(mpath, "w"), ensure_ascii=False)
        report(man)


if __name__ == "__main__":
    main()