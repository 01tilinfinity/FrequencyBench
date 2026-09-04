import requests, time, json, os, csv
from tqdm import tqdm

EP = "https://query.wikidata.org/sparql"
CONTACT = os.environ.get("WDQS_CONTACT", "hs01151116@korea.ac.kr")
H = {"User-Agent": f"FrequencyBench/0.1 ({CONTACT})"}

OUT = "wd_scan"
os.makedirs(OUT, exist_ok=True)

PROBE_TIMEOUT = 20      # Stage 2: 이 안에 답 못 하면 대형 property로 간주
PAGE_INIT = 5000        # Stage 3: 시작 페이지 크기
PAGE_MIN  = 250         # 여기까지 줄여도 안 되면 부분 수집으로 종료
MAX_ROWS  = 3_000_000   # property당 상한


def query(q, timeout=120, tries=5):
    """returns (status, data). status: ok | timeout | error"""
    for i in range(tries):
        try:
            r = requests.get(EP, params={"query": q, "format": "json"},
                             headers=H, timeout=timeout)
            if r.status_code == 200:
                return "ok", r.json()
            if r.status_code in (429, 503):                 # rate limit
                time.sleep(20 * (i + 1)); continue
            if r.status_code in (500, 502, 504):            # 쿼리가 무거움
                if i >= 1 or tries == 1:
                    return "timeout", None
                time.sleep(5); continue
            return "error", r.status_code
        except requests.exceptions.Timeout:
            if i >= 1 or tries == 1:
                return "timeout", None
            time.sleep(5)
        except requests.exceptions.RequestException:        # 네트워크 문제
            if i == tries - 1:
                return "error", "network"
            time.sleep(15 * (i + 1))
        except Exception as e:
            return "error", str(e)
    return "timeout", None


# ---------------------------------------------------------------- Stage 1
def stage1():
    path = f"{OUT}/1_properties.json"
    if os.path.exists(path):
        d = json.load(open(path)); print(f"[1] cached: {len(d)} properties"); return d

    q = """
    SELECT ?p ?pLabel ?type WHERE {
      ?p wikibase:propertyType ?type .
      FILTER(?type IN (wikibase:WikibaseItem, wikibase:Quantity))
      SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
    }
    """
    st, data = query(q, timeout=180, tries=5)
    if st != "ok":
        raise SystemExit(f"[1] failed: {st} {data}")
    props = [{"pid": b["p"]["value"].split("/")[-1],
              "label": b.get("pLabel", {}).get("value", ""),
              "type": b["type"]["value"].split("#")[-1]}
             for b in data["results"]["bindings"]]
    props.sort(key=lambda x: int(x["pid"][1:]))
    json.dump(props, open(path, "w"), ensure_ascii=False, indent=1)
    print(f"[1] {len(props)} properties")
    return props


# ---------------------------------------------------------------- Stage 2
PROBE_Q = "SELECT ?t WHERE {{ ?i p:{p} ?st . ?st pq:{q} ?t . }} LIMIT 1"


def stage2(props):
    path, seen = f"{OUT}/2_temporal_properties.json", f"{OUT}/2_checked.json"
    res = json.load(open(path)) if os.path.exists(path) else {}
    checked = set(json.load(open(seen))) if os.path.exists(seen) else set()
    todo = [p for p in props if p["pid"] not in checked]
    print(f"[2] {len(checked)} checked, {len(res)} kept, {len(todo)} to go")

    pbar = tqdm(todo, desc="[2] probe", unit="p")
    for i, p in enumerate(pbar):
        pid, has = p["pid"], {}
        for qual in ("P580", "P582"):
            st, data = query(PROBE_Q.format(p=pid, q=qual),
                             timeout=PROBE_TIMEOUT, tries=1)
            if st == "ok":
                has[qual] = len(data["results"]["bindings"]) > 0
            else:
                has[qual] = True          # timeout = 대형 property → 있다고 간주
            time.sleep(0.1)

        checked.add(pid)
        if has["P580"] or has["P582"]:
            res[pid] = {**p, **has}

        pbar.set_postfix(kept=len(res))
        if i % 20 == 0:
            json.dump(res, open(path, "w"), ensure_ascii=False)
            json.dump(sorted(checked), open(seen, "w"))

    json.dump(res, open(path, "w"), ensure_ascii=False)
    json.dump(sorted(checked), open(seen, "w"))
    print(f"[2] {len(res)} properties have P580/P582")
    return res


# ---------------------------------------------------------------- Stage 3
HARVEST_Q = """
SELECT ?i ?v ?start ?sprec ?end ?eprec ?rank WHERE {{
  ?i p:{p} ?st .
  ?st ps:{p} ?v ; wikibase:rank ?rank .
  OPTIONAL {{ ?st pqv:P580 ?sn . ?sn wikibase:timeValue ?start ;
                                    wikibase:timePrecision ?sprec . }}
  OPTIONAL {{ ?st pqv:P582 ?en . ?en wikibase:timeValue ?end ;
                                    wikibase:timePrecision ?eprec . }}
  FILTER(BOUND(?start) || BOUND(?end))
}}
LIMIT {lim} OFFSET {off}
"""


def parse(x, pid):
    v = x["v"]["value"]
    return {"subject": x["i"]["value"].split("/")[-1],
            "property": pid,
            "value": v.split("/")[-1] if "/entity/" in v else v,
            "value_type": "item" if "/entity/Q" in v else "literal",
            "start": x.get("start", {}).get("value"),
            "start_prec": x.get("sprec", {}).get("value"),
            "end": x.get("end", {}).get("value"),
            "end_prec": x.get("eprec", {}).get("value"),
            "rank": x["rank"]["value"].split("#")[-1]}


def harvest_one(pid, ddir, state, pbar):
    """페이지 단위로 즉시 append. 타임아웃이면 페이지 축소 후 같은 offset 재시도."""
    fp = f"{ddir}/{pid}.jsonl"
    off  = state.get("offset", 0)
    page = state.get("page", PAGE_INIT)
    n    = state.get("n", 0)

    if off == 0 and os.path.exists(fp):
        os.remove(fp)

    while n < MAX_ROWS:
        st, data = query(HARVEST_Q.format(p=pid, lim=page, off=off),
                         timeout=180, tries=3)

        if st == "timeout":
            if page > PAGE_MIN:
                page = max(PAGE_MIN, page // 2)
                pbar.set_postfix(pid=pid, n=n, page=page, note="shrink")
                time.sleep(3)
                continue
            return n, "partial", off, page

        if st != "ok":
            return n, "error", off, page

        b = data["results"]["bindings"]
        if b:
            with open(fp, "a", encoding="utf-8") as f:
                for x in b:
                    f.write(json.dumps(parse(x, pid), ensure_ascii=False) + "\n")
            n += len(b)
            off += len(b)

        pbar.set_postfix(pid=pid, n=n, page=page)

        if len(b) < page:
            return n, "ok", off, page

        if page < PAGE_INIT:
            page = min(PAGE_INIT, page * 2)
        time.sleep(0.4)

    return n, "maxrows", off, page


def stage3(temporal):
    ddir = f"{OUT}/data"; os.makedirs(ddir, exist_ok=True)
    logp = f"{OUT}/3_harvest_log.json"
    log = json.load(open(logp)) if os.path.exists(logp) else {}

    todo = [pid for pid in temporal
            if log.get(pid, {}).get("status") not in ("ok", "maxrows")]
    print(f"[3] {len(log)} logged, {len(todo)} to harvest/resume")

    pbar = tqdm(todo, desc="[3] harvest", unit="p")
    for pid in pbar:
        prev = log.get(pid, {})
        state = {"offset": prev.get("offset", 0),
                 "page":   prev.get("page", PAGE_INIT),
                 "n":      prev.get("n", 0)}
        n, status, off, page = harvest_one(pid, ddir, state, pbar)
        log[pid] = {"n": n, "status": status, "offset": off, "page": page,
                    "label": temporal[pid]["label"]}
        json.dump(log, open(logp, "w"), ensure_ascii=False)
        time.sleep(0.3)
    return log


# ---------------------------------------------------------------- report
def report(log):
    path = f"{OUT}/harvest_report.csv"
    rows = sorted(({"pid": k, **v} for k, v in log.items()), key=lambda r: -r["n"])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["pid", "label", "n", "status", "offset", "page"])
        w.writeheader(); w.writerows(rows)
    tot = sum(r["n"] for r in rows)
    bad = [r for r in rows if r["status"] not in ("ok", "maxrows")]
    print(f"\nwrote {path}")
    print(f"total: {tot:,} statements / {len(rows)} properties / {len(bad)} incomplete")
    print(f"\n{'pid':<8}{'label':<36}{'n':>10}  status")
    for r in rows[:40]:
        print(f"{r['pid']:<8}{r['label'][:35]:<36}{r['n']:>10}  {r['status']}")


if __name__ == "__main__":
    report(stage3(stage2(stage1())))