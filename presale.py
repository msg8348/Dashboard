"""분양권 단지 페이지 (/{시도}/pre/{청약홈 주택관리번호}.html).

- 청약홈: 입주예정월 · 타입(84A…)별 공급세대 · 최고 분양가
- 입주자모집공고문(PDF): 타입·층별 분양가, 총 세대수 (notice.py) — 못 읽으면 최고 분양가 기준
- 분양권 실거래: 최근 13개월(store/pre) + 과거(history 브랜치 pre_{시도}.json.gz, 2020년~)
"""
import gzip
import json
import os
from collections import defaultdict

import notice

PRE_DIR = "pre"


def label_of(types, area):
    """거래 전용면적 → 청약홈 약식표기 (가장 가까운 주택형, 같은 평형 안에서만)."""
    best = None
    for t in types:
        d = abs(t[4] - area)
        if int(t[4]) == int(area) or d < 1:
            if best is None or d < best[0]:
                best = (d, t)
    return best[1] if best else None


def load_hist(hist_dir, key):
    p = os.path.join(hist_dir, f"pre_{key}.json.gz")
    if not os.path.exists(p):
        return {}
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return json.load(f).get("apts", {})


def _fl(f):
    return int(f) if str(f).lstrip("-").isdigit() else 0


def build(sd, sdir, sdb, hist_dir, oldest_ym, now, env, site, l2slug, l2_of, houses, match_house, store, site_url):
    """시도 하나의 분양권 페이지. (주택관리번호 집합, 검색 목록, 주소 목록) 반환."""
    by = defaultdict(list)          # 주택관리번호 → [[계약일, 금액, 층, 면적]]
    hmap = {h["id"]: h for h in houses}
    for t in sdb["pre"]["trades"]:
        h = match_house(houses, sd, t)
        if h:
            by[h["id"]].append([int(t["dt"]), t["p"], _fl(t["f"]), t["a"]])
    for a in load_hist(hist_dir, sd["key"]).values():
        t = {"d": sd["codes"].get(a["c"], ""), "n": a["n"]}
        h = match_house(houses, sd, t)
        if h:
            by[h["id"]] += [[int(x[0]), x[1], _fl(x[2]), x[4]] for x in a["t"] if str(x[0])[:6] < oldest_ym]
    npath = os.path.join(store, "notice.json")
    cache = notice.load(npath)
    budget = [int(os.environ.get("NOTICE_MAX", "40"))]
    tpl = env.get_template("pre.html")
    out_dir = os.path.join(site, sdir, PRE_DIR)
    os.makedirs(out_dir, exist_ok=True)
    l2_name = {l["key"]: l["name"] for l in sd["l2"]}
    done, search, urls = set(), [], []
    for hid, rows in sorted(by.items(), key=lambda kv: -len(kv[1])):
        h = hmap[hid]
        types = [t for t in h.get("types", []) if len(t) >= 5]
        if not types:
            continue
        nt = notice.get(h, cache, now.replace(tzinfo=None), budget) or {}
        prices = nt.get("prices") or {}   # 읽은 타입만 층별, 나머지는 최고 분양가
        trades = []
        for dt, p, f, a in sorted(rows, key=lambda r: -r[0]):
            t = label_of(types, a)
            if not t:
                continue
            base = notice.price_at(prices, t[2], f) if prices else 0
            trades.append([dt, p, f, t[2], base or t[3], 1 if base else 0])
        if not trades:
            continue
        gu = next((n for c, n in sd["codes"].items() if n.split()[-1] in h["addr"]), "")
        code = next((c for c, n in sd["codes"].items() if n == gu), "")
        crumbs = [("전국", "../../index.html"), (sd["short"], "../index.html")]
        l2k = l2_of.get(code)
        if l2k and len(sd["l2"]) > 1:
            crumbs.append((l2_name[l2k], f"../{l2slug[l2k]}.html"))
        crumbs.append((h["name"], None))
        mv = h.get("mvn") or ""
        gen = sum(t[1] for t in types)
        total = nt.get("total") if nt.get("total", 0) >= gen else 0
        hh = f"총 {total:,}세대 (일반분양 {h.get('total') or gen:,})" if total and total != (h.get("total") or gen) else f"분양 {h.get('total') or gen:,}세대"
        meta = " · ".join(x for x in ("분양권", f"{mv[:4]}년 {int(mv[4:6])}월 입주예정" if len(mv) == 6 else "", hh) if x)
        data = {"ty": [[t[2], t[1], t[3]] for t in types], "t": trades, "scan": sorted(prices),
                "rng": {l: [min(r[2] for r in v), max(r[2] for r in v)] for l, v in (prices or {}).items()}}
        ctx = {"name": h["name"], "fav": [h["name"], f"{sd['short']} {gu} · 분양권", f"{sdir}/{PRE_DIR}/{hid}.html"], "addr": h["addr"].replace(sd["sido"], sd["short"]), "meta": meta, "crumbs": crumbs,
               "root": "../../", "today": now.strftime("%Y%m%d"), "data": data, "map_q": f"{h['addr']} {h['name']}",
               "info": {"gen": h.get("total") or gen, "total": total, "mv": f"{mv[:4]}.{mv[4:]}" if len(mv) == 6 else "-",
                        "pbl": (h.get("pbl") or "")[:7].replace("-", "."), "builder": h.get("builder") or "-", "n": len(trades)},
               "page_url": f"{site_url}/{sdir}/{PRE_DIR}/{hid}.html",
               "seo_title": f"{h['name']} 분양권 실거래가·프리미엄 ({sd['short']} {gu}) | 옆집얼마",
               "seo_desc": f"{h['name']} 분양권 실거래가와 타입·층별 분양가 대비 프리미엄, 입주예정 {mv[:4]}년 — 옆집얼마"}
        with open(os.path.join(out_dir, f"{hid}.html"), "w", encoding="utf-8") as f:
            f.write(tpl.render(ctx))
        done.add(hid)
        search.append([h["name"], f"{sd['short']} {gu} · 분양권".strip(), f"{sdir}/{PRE_DIR}/{hid}.html", len(trades)])
        urls.append(ctx["page_url"])
    notice.save(npath, cache)
    scanned = sum(1 for hid in done if (cache.get(hid) or {}).get("prices"))
    print(f"🏗️ {sd['short']}: 분양권 페이지 {len(done)}개 (상세 분양가 읽음 {scanned}개)")
    return done, search, urls
