"""단지 페이지 (/{시도}/apt/{단지번호}.html) 생성.

- 매매: 과거 실거래(history 브랜치, 2006년~) + 최근 13개월(store/sale)
- 전월세: 최근 13개월(store/rent)
- 단지 기본정보: K-apt (지번 → 같은 법정동 단지명 순으로 찾음)
단지번호 = 국토부 단지 일련번호(aptSeq, 예: 26350-123). 데이터는 페이지에 넣고, 그리기는 static/apt.js 가 한다.
"""
import gzip
import json
import os
import re
from collections import defaultdict

import kapt
import poi
import schoolzone

APT_DIR = "apt"


def _jn(s):
    """지번 표기 맞춤: '1068-' → '1068', '12-0' → '12'."""
    s = (s or "").strip().rstrip("-")
    return re.sub(r"-0+$", "", s)


def kapt_index(sido):
    """K-apt 단지: (법정동, 지번) 색인과 법정동별 목록."""
    by_lot, by_dong = defaultdict(list), defaultdict(list)
    for r in kapt.load():
        if r["sido"] != sido:
            continue
        m = re.search(r" (산?\d[\d-]*)", r["jibun_addr"] or "")
        if m:
            by_lot[(r["dongri"], _jn(m.group(1)))].append(r)
        by_dong[r["dongri"]].append(r)
    return by_lot, by_dong


def find_kapt(idx, u, j, name, ckey):
    by_lot, by_dong = idx
    dong = (u or "").split()[-1] if u else ""
    rows = by_lot.get((dong, _jn(j)))
    if rows:
        return rows
    k = ckey(name)
    if not k:
        return []
    same = [r for r in by_dong.get(dong, []) if ckey(r["name"]) == k]
    return same or [r for r in by_dong.get(dong, []) if k in ckey(r["name"]) or ckey(r["name"]) in k][:1]


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def info_from(rows, sido):
    """K-apt 행(1·2단지 등 여러 개면 합산) → 화면용 기본정보."""
    if not rows:
        return {}
    r0 = max(rows, key=lambda r: r["households"])
    hh = sum(r["households"] for r in rows)
    bd = sum(_int(r["buildings"]) for r in rows)
    mf = max(_int(r["max_floor"]) for r in rows)
    pk = sum(_int(r["parking"]) for r in rows)
    ad = min((r["approval_date"] or "99999999") for r in rows)
    road = (r0.get("road_addr") or "").replace(sido, "").strip()
    road = re.sub(r"^\S+[시군구] (\S+구 )?", "", road)     # '금정구 금강로 271' → '금강로 271'
    return {"hh": hh, "bd": bd, "mf": mf, "bl": (r0.get("builder") or "").strip(), "pk": round(pk / hh, 1) if hh and pk else 0,
            "ht": (r0.get("heating") or "").strip(), "cr": (r0.get("corridor") or "").strip(),
            "ad": ad if ad != "99999999" else "", "road": road, "kind": r0.get("kind") or "아파트"}


def load_hist(hist_dir, key):
    p = os.path.join(hist_dir, f"{key}.json.gz")
    if not os.path.exists(p):
        return {}
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return json.load(f).get("apts", {})


def _fl(f):
    return int(f) if str(f).lstrip("-").isdigit() else 0


def collect(hist, sale, rent, oldest_ym):
    """단지번호별 {n, c, u, j, by, s: [[계약일, 금액, 층, 동, 면적, 등기]], r: [[계약일, 보증금, 월세, 층, 면적]]}."""
    apts = {}
    for k, a in hist.items():
        if "|" in k:          # 단지번호가 없는 옛 거래는 묶기 어려워 제외
            continue
        apts[k] = {"n": a["n"], "c": a["c"], "u": a.get("u", ""), "j": a.get("j", ""), "by": a.get("by", ""),
                   "s": [[int(x[0]), x[1], _fl(x[2]), x[3] or "", x[4], x[5] or ""] for x in a["t"] if str(x[0])[:6] < oldest_ym],
                   "r": []}
    for t in sale:
        k = t.get("s")
        if not k:
            continue
        a = apts.setdefault(k, {"n": t["n"], "c": t.get("c", ""), "u": t.get("u", ""), "j": t.get("j", ""),
                                "by": t.get("by", ""), "s": [], "r": []})
        a["n"] = t["n"]                       # 최근 이름 우선
        if t.get("by") and not a["by"]:
            a["by"] = t["by"]
        if t.get("j") and not a["j"]:
            a["j"] = t["j"]
        a["s"].append([int(t["dt"]), t["p"], _fl(t["f"]), t.get("dong", ""), t["a"], t.get("rg", "")])
    for t in rent:
        k = t.get("s")
        if not k:
            continue
        a = apts.setdefault(k, {"n": t["n"], "c": t.get("c", ""), "u": t.get("u", ""), "j": "", "by": "", "s": [], "r": []})
        a["r"].append([int(t["dt"]), t["p"], t.get("m") or 0, _fl(t["f"]), t["a"]])
    for a in apts.values():
        a["s"].sort(key=lambda x: -x[0])
        a["r"].sort(key=lambda x: -x[0])
    return apts


NUM = re.compile(r"(제?\d+단지|\d+차)\)?$")


def merge_split(apts, ckey):
    """국토부가 한 단지를 'OO아파트'(입주 초기)와 'OO1단지'로 따로 등록한 경우: 번호 없는 쪽을 같은 법정동의
    같은 이름 번호 단지 중 거래가 가장 많은 곳에 합친다. {합쳐진 단지번호: 대표 단지번호} 반환."""
    groups = defaultdict(list)
    for k, a in apts.items():
        groups[(a["c"], a["u"], ckey(a["n"]))].append(k)
    alias = {}
    for ks in groups.values():
        if len(ks) < 2:
            continue
        numbered = [k for k in ks if NUM.search(apts[k]["n"].replace(" ", ""))]
        plain = [k for k in ks if k not in numbered]
        if not numbered or not plain:
            continue
        to = max(numbered, key=lambda k: len(apts[k]["s"]) + len(apts[k]["r"]))
        for k in plain:
            a, b = apts.pop(k), apts[to]
            b["s"] = sorted(b["s"] + a["s"], key=lambda x: -x[0])
            b["r"] = sorted(b["r"] + a["r"], key=lambda x: -x[0])
            b["by"] = b["by"] or a["by"]
            alias[k] = to
    return alias


RANK_TYPES = ("59", "74", "84")
RANK_MIN = 1   # 최근 1년 해당 타입 거래 1건 이상이면 순위에 포함


def price_ranks(apts, now):
    """59·74(70~77㎡)·84 타입별 시도 내 매매가 순위 (최근 1년 개별 거래 최고가 기준, 10위까지). {단지번호: [[타입, 순위, '13.2억', 거래수, 비교 단지 수]]}"""
    from datetime import timedelta
    d365 = int((now - timedelta(days=365)).strftime("%Y%m%d"))
    pool = {g: [] for g in RANK_TYPES}
    for k, a in apts.items():
        by = defaultdict(list)
        for t in a["s"]:
            if t[0] >= d365 and not (len(t) > 6 and t[6]):   # 분양권(입주 후 합친 거래)은 제외
                ai = int(t[4])
                g = "59" if ai == 59 else "74" if 70 <= ai <= 77 else "84" if ai == 84 else ""   # 74 타입 = 전용 70~77㎡
                if g in pool:
                    by[g].append(t[1])
        for g, ps in by.items():
            if len(ps) >= RANK_MIN:
                pool[g].append((max(ps), k, len(ps)))   # 개별 거래 중 최고가 기준
    out = defaultdict(list)
    for g in RANK_TYPES:
        lst = sorted(pool[g], reverse=True)
        for i, (avg, k, n) in enumerate(lst[:10]):
            out[k].append([g, i + 1, f"{avg / 10000:.1f}억", n, len(lst)])
    return out


def build(sd, sdir, sdb, hist_dir, oldest_ym, now, env, site, l2slug, l2_of, ckey, site_url, store="store", pre=None):
    """pre {주택관리번호: (청약홈 단지, 분양권 거래)}: 입주예정월이 지난 분양권 — 같은 시군구·같은 이름의 매매 단지가
    있으면 그 단지 거래에 분양권 거래를 합친다. 반환: (단지번호 집합, 검색 목록, 주소 목록, {주택관리번호: 단지번호})."""
    """시도 하나의 단지 페이지를 만들고 (단지번호 집합, 검색 목록, 주소 목록) 반환."""
    hist = load_hist(hist_dir, sd["key"])
    if not hist:
        return set(), [], [], {}
    apts = collect(hist, sdb["sale"]["trades"], sdb["rent"]["trades"], oldest_ym)
    alias = merge_split(apts, ckey)
    moved = {}
    if pre:
        names = defaultdict(list)
        for k, a in apts.items():
            if a["s"]:
                names[(a["c"], ckey(a["n"]))].append(k)
        codes = {c: n for c, n in sd["codes"].items()}
        for hid, (h, rows) in pre.items():
            gu = next((n for c, n in codes.items() if n.split()[-1] in h["addr"]), "")
            c = next((c for c, n in codes.items() if n == gu), "")
            ks = names.get((c, ckey(h["name"])))
            if not ks:
                continue
            k = max(ks, key=lambda x: len(apts[x]["s"]))
            apts[k]["s"] = sorted(apts[k]["s"] + [[dt, p, f, "", a, "", 1] for dt, p, f, a in rows], key=lambda x: -x[0])
            moved[hid] = k
        if moved:
            print(f"🔁 {sd['short']}: 입주한 분양권 {len(moved)}곳 거래를 매매 단지로 옮김")
    idx = kapt_index(sd["sido"])
    ppath = os.path.join(store, "poi.json")   # 주변 정보 (카카오·TAGO) — 거래 많은 단지부터 조금씩 채움
    pcache = poi.load(ppath)
    order = sorted(apts, key=lambda k: -(len(apts[k]["s"]) + len(apts[k]["r"])))
    poi.update(pcache, {k: (f"{sd['short']} {sd['codes'].get(apts[k]['c'], '')} {apts[k]['u']} {apts[k]['j']}".strip(), apts[k]["n"])
                        for k in order if apts[k]["j"]}, now, budget=int(os.environ.get("POI_MAX", "1500")))
    zones = schoolzone.load(store, sd["key"], now.replace(tzinfo=None))   # 배정 초등학교 (통학구역)
    poi.assign(pcache, order, zones, "z2")
    poi.save(ppath, pcache)
    ranks = price_ranks(apts, now)
    tpl = env.get_template("apt.html")
    out_dir = os.path.join(site, sdir, APT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    l2_name = {l["key"]: l["name"] for l in sd["l2"]}
    done, search, urls = set(), [], []
    for k, a in apts.items():
        if not a["s"] and not a["r"]:
            continue
        gu = sd["codes"].get(a["c"], "")
        info = info_from(find_kapt(idx, a["u"], a["j"], a["n"], ckey), sd["sido"])
        l2k = l2_of.get(a["c"])
        crumbs = [("전국", "../../index.html"), (sd["short"], "../index.html")]
        if l2k and len(sd["l2"]) > 1:
            crumbs.append((l2_name[l2k], f"../{l2slug[l2k]}.html"))
        crumbs.append((a["n"], None))
        loc = " ".join(x for x in (sd["short"], gu, a["u"]) if x)
        ad = info.get("ad") or ""
        built = (f"{ad[2:4]}년 {int(ad[4:6])}월" if len(ad) >= 6 else
                 f"{str(a['by'])[2:]}년" if a["by"] else "")
        year = int(ad[:4]) if ad else (int(a["by"]) if str(a["by"]).isdigit() else 0)
        age = f"{now.year - year + 1}년차" if year and year <= now.year else ("입주예정" if year else "")
        data = {"s": a["s"], "r": a["r"], "by": year, "hh": info.get("hh", 0)}
        ctx = {"ranks": ranks.get(k, []), "sido_short": sd["short"], "name": a["n"], "loc": loc, "loc2": " ".join(x for x in (gu, a["u"]) if x), "poi": pcache.get(k) if (pcache.get(k) or {}).get("x") else None, "fav": [a["n"], f"{sd['short']} {gu} {a['u']}".strip(), f"{sdir}/{APT_DIR}/{k}.html"], "jibun": a["j"], "road": info.get("road", ""), "info": info,
               "meta": " · ".join(x for x in ("" if (info.get("kind") or "아파트") == "아파트" else info["kind"], built, age) if x),
               "crumbs": crumbs, "root": "../../", "data": data, "today": now.strftime("%Y%m%d"),
               "map_q": f"{sd['short']} {gu} {a['u']} {a['n']}".replace("  ", " "),
               "page_url": f"{site_url}/{sdir}/{APT_DIR}/{k}.html",
               "seo_title": f"{a['n']} 실거래가 ({sd['short']} {gu} {a['u']}) | 옆집얼마",
               "seo_desc": f"{sd['short']} {gu} {a['u']} {a['n']} 아파트 매매·전월세 실거래가와 시세 흐름 — 2006년부터 평형별 거래 내역, 신고가, 거래량 | 옆집얼마"}
        with open(os.path.join(out_dir, f"{k}.html"), "w", encoding="utf-8") as f:
            f.write(tpl.render(ctx))
        done.add(k)
        search.append([a["n"], f"{sd['short']} {gu} {a['u']}".strip(), f"{sdir}/{APT_DIR}/{k}.html", len(a["s"])])
        urls.append(ctx["page_url"])
    for k, to in alias.items():   # 합친 단지번호 → 대표 단지 페이지로 이동
        if to in done:
            with open(os.path.join(out_dir, f"{k}.html"), "w", encoding="utf-8") as f:
                f.write(f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url={to}.html">'
                        f'<link rel="canonical" href="{to}.html"><script>location.replace("{to}.html")</script>')
            done.add(k)
    print(f"🏢 {sd['short']}: 단지 페이지 {len(done):,}개 (K-apt 정보 연결 포함)")
    return done, search, urls, moved
