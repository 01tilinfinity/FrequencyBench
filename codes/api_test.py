import requests, json

H = {"User-Agent": "FrequencyBench/0.1 (hs01151116@korea.ac.kr)"}
API = "https://www.wikidata.org/w/api.php"


def label(qid):
    if not isinstance(qid, str) or not qid.startswith("Q"):
        return qid
    r = requests.get(API, params={"action": "wbgetentities", "ids": qid,
                                  "props": "labels", "languages": "en",
                                  "format": "json"}, headers=H)
    try:
        return r.json()["entities"][qid]["labels"]["en"]["value"]
    except Exception:
        return qid


def show(qid, pid, resolve=True):
    r = requests.get(API, params={"action": "wbgetentities", "ids": qid,
                                  "props": "claims", "format": "json"}, headers=H)
    claims = r.json()["entities"][qid]["claims"].get(pid, [])
    print(f"\n=== {label(qid)} ({qid})  {pid}: {len(claims)} statements ===")

    rows = []
    for c in claims:
        dv = c["mainsnak"].get("datavalue", {}).get("value", {})
        v = dv.get("id") if isinstance(dv, dict) else dv
        q = c.get("qualifiers", {})

        def t(p):
            try:
                return q[p][0]["datavalue"]["value"]["time"][1:11]
            except Exception:
                return None

        rows.append({
            "value": label(v) if resolve else v,
            "start": t("P580"),
            "end":   t("P582"),
            "rank":  c["rank"],
            "quals": sorted(k for k in q if k not in ("P580", "P582")),
        })

    rows.sort(key=lambda r: r["start"] or "0000")
    for r in rows:
        print(f"  {str(r['start']):<12} ~ {str(r['end'] or 'present'):<12} "
              f"{r['value'][:38]:<40} [{r['rank']}] {r['quals']}")

    # 구간 겹침 검사
    iv = [(r["start"], r["end"] or "9999-12-31") for r in rows if r["start"]]
    overlaps = [(a, b) for i, a in enumerate(iv) for b in iv[i+1:]
                if a[0] < b[1] and b[0] < a[1]]
    print(f"  → overlapping pairs: {len(overlaps)}"
          f"{' (ACCUMULATIVE)' if overlaps else ' (REPLACIVE)'}")


# 임대 이적이 있는 축구선수 — 구간 겹침 예상
show("Q142794", "P54")     # Kylian Mbappé

# 비교용: 순수 교체형
show("Q95", "P169")        # Google, CEO