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
DAN = re.compile(r"\(?제?\d+단지\)?$")


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
    # 'OO1단지 · OO2단지 · OO3단지'(같은 법정동·같은 이름): 단지 번호를 떼고 한 단지로 합친다 ('N차'는 별개 단지라 그대로)
    groups = defaultdict(list)
    for k, a in apts.items():
        if DAN.search(a["n"].replace(" ", "")):
            groups[(a["c"], a["u"], ckey(a["n"]))].append(k)
    for ks in groups.values():
        if len(ks) < 2:
            continue
        to = max(ks, key=lambda k: len(apts[k]["s"]) + len(apts[k]["r"]))
        b = apts[to]
        b["mem"] = [(apts[k]["j"], apts[k]["n"]) for k in ks]   # K-apt 세대수 합산용
        b["n"] = DAN.sub("", b["n"]).strip() or b["n"]
        for k in ks:
            if k == to:
                continue
            a = apts.pop(k)
            b["s"] = sorted(b["s"] + a["s"], key=lambda x: -x[0])
            b["r"] = sorted(b["r"] + a["r"], key=lambda x: -x[0])
            b["by"] = min(x for x in (b["by"], a["by"]) if x) if (b["by"] or a["by"]) else b["by"]
            alias[k] = to
    # 동·구가 달라도: 이름에 '(OO동)'이 붙은 같은 이름(6글자 이상)은 한 단지로 (예: 래미안포레스티지1단지(장전동) → 래미안포레스티지)
    PAREN = re.compile(r"\([^)]*[동리가]\)$")   # 괄호 안이 동 이름일 때만 (번지 등은 다른 단지)
    base = lambda n: DAN.sub("", PAREN.sub("", n.replace(" ", ""))) or n
    groups = defaultdict(list)
    for k, a in apts.items():
        groups[ckey(base(a["n"]))].append(k)
    for key, ks in groups.items():
        if len(ks) < 2 or len(key) < 6:
            continue
        # 동이 다른데 합치는 건 이름에 '(OO동)'이 직접 붙은 경우만 (예: 명륜아이파크2단지(복천동)는 명륜아이파크와 다른 단지)
        if not any(PAREN.search(apts[k]["n"].replace(" ", "")) for k in ks):
            continue
        tail = lambda k: PAREN.search(apts[k]["n"].replace(" ", "")) or DAN.search(apts[k]["n"].replace(" ", "")) or apts[k].get("mem")
        if sum(1 for k in ks if not tail(k)) > 1:
            continue   # 꼬리 없는 같은 이름이 여럿이면 체인 브랜드(다른 단지)일 수 있어 그대로
        to = max(ks, key=lambda k: len(apts[k]["s"]) + len(apts[k]["r"]))
        b = apts[to]
        b["mem"] = (b.get("mem") or [(b["j"], b["n"])]) + [m for k in ks if k != to for m in (apts[k].get("mem") or [(apts[k]["j"], apts[k]["n"])])]
        b["n"] = base(b["n"]) if len(base(b["n"])) >= 2 else b["n"]
        for k in ks:
            if k == to:
                continue
            a = apts.pop(k)
            b["s"] = sorted(b["s"] + a["s"], key=lambda x: -x[0])
            b["r"] = sorted(b["r"] + a["r"], key=lambda x: -x[0])
            alias[k] = to
    for k, to in list(alias.items()):   # 두 단계로 합쳐진 곳은 최종 대표로
        while to in alias:
            to = alias[to]
        alias[k] = to
    return alias


RANK_TYPES = ("59", "74", "84")
RANK_MIN = 1   # 최근 1년 해당 타입 거래 1건 이상이면 순위에 포함


PRE_RANKS = {}   # 분양권 단지 {주택관리번호: 순위} — presale.build 에서 씀


def price_ranks(apts, now, pre_rows=None):
    """59·74(70~77㎡)·84 타입별 시도 내 매매가 순위 (최근 1년 개별 거래 최고가 기준, 20위까지) — 분양권 포함.
    pre_rows {주택관리번호: [[계약일, 금액, 층, 면적]]}: 매매 단지로 합쳐지지 않은 분양권 단지 (키 ('pre', 주택관리번호)).
    최근 1년 = 최고가 페이지 '최근1년'과 같은 월 단위 (작년 다음 달 ~ 이번 달).
    {단지번호: [[타입, 순위, '13.2억', 거래수, 비교 단지 수]]}"""
    y, m = now.year - 1, now.month + 1
    if m == 13:
        y, m = y + 1, 1
    d365 = (y * 100 + m) * 100
    pool = {g: [] for g in RANK_TYPES}
    src = [(k, [(t[0], t[1], t[4]) for t in a["s"]]) for k, a in apts.items()]
    src += [(("pre", hid), [(r[0], r[1], r[3]) for r in rows]) for hid, rows in (pre_rows or {}).items()]
    for k, rows in src:
        by = defaultdict(list)
        for dt, p, area in rows:
            if dt >= d365:
                ai = int(area)
                g = "59" if ai == 59 else "74" if 70 <= ai <= 77 else "84" if ai == 84 else ""   # 74 타입 = 전용 70~77㎡
                if g in pool:
                    by[g].append(p)
        for g, ps in by.items():
            if len(ps) >= RANK_MIN:
                pool[g].append((max(ps), k, len(ps)))   # 개별 거래 중 최고가 기준
    out = defaultdict(list)
    for g in RANK_TYPES:
        lst = sorted(pool[g], key=lambda x: -x[0])
        for i, (avg, k, n) in enumerate(lst[:20]):
            out[k].append([g, i + 1, f"{avg / 10000:.1f}억", n, len(lst)])
    return out


def type_labels(sd, houses, ckey):
    """청약홈 단지 → {(시군구코드, 이름키): [[전용면적, '84A'], ...]} (글자 있는 타입만)."""
    out = {}
    for h in houses or []:
        ty = [[t[4], t[2]] for t in h.get("types", []) if len(t) >= 5 and t[2][-1:].isalpha()]
        if not ty:
            continue
        gu = next((n for c, n in sd["codes"].items() if n.split()[-1] in h["addr"]), "")
        code = next((c for c, n in sd["codes"].items() if n == gu), "")
        if code:
            out.setdefault((code, ckey(h["name"])), []).extend(ty)
    return out


def build(sd, sdir, sdb, hist_dir, oldest_ym, now, env, site, l2slug, l2_of, ckey, site_url, store="store", pre=None, houses=None, pre_all=None):
    """pre {주택관리번호: (청약홈 단지, 분양권 거래)}: 입주예정월이 지난 분양권 — 같은 시군구·같은 이름의 매매 단지가
    있으면 그 단지 거래에 분양권 거래를 합친다. 반환: (단지번호 집합, 검색 목록, 주소 목록, {주택관리번호: 단지번호})."""
    """시도 하나의 단지 페이지를 만들고 (단지번호 집합, 검색 목록, 주소 목록) 반환."""
    hist = load_hist(hist_dir, sd["key"])
    if not hist:
        return set(), [], [], {}, {}
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
    poi.assign(pcache, order, zones, "z3")
    poi.amen(pcache, order, "a1", budget=int(os.environ.get("AMEN_MAX", "1500")))   # 학원가·상권 (나의 예산)
    poi.save(ppath, pcache)
    ranks = price_ranks(apts, now, {hid: rows for hid, rows in (pre_all or {}).items() if hid not in moved})
    PRE_RANKS.clear()
    PRE_RANKS.update({k[1]: v for k, v in ranks.items() if isinstance(k, tuple)})
    tlab = type_labels(sd, houses, ckey)
    tpl = env.get_template("apt.html")
    out_dir = os.path.join(site, sdir, APT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    l2_name = {l["key"]: l["name"] for l in sd["l2"]}
    done, search, urls = set(), [], []
    for k, a in apts.items():
        if not a["s"] and not a["r"]:
            continue
        gu = sd["codes"].get(a["c"], "")
        if a.get("mem"):   # 1·2·3단지를 합친 단지: 각 단지 K-apt 행을 모아 합산
            rows, seen = [], set()
            for j, nm in a["mem"]:
                for r in find_kapt(idx, a["u"], j, nm, ckey):
                    if id(r) not in seen:
                        seen.add(id(r))
                        rows.append(r)
            info = info_from(rows, sd["sido"])
        else:
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
        lab = tlab.get((a["c"], ckey(a["n"])))
        if lab:   # 청약홈 분양 단지: 거래 면적 → 84A 같은 타입 (면적이 정확히 같을 때만)
            areas = {x[4] for x in a["s"]} | {x[4] for x in a["r"]}
            tl = {}
            for ar in areas:
                m = min(lab, key=lambda t: abs(t[0] - ar))
                if abs(m[0] - ar) < 0.006:
                    tl[str(ar)] = m[1]
            if tl:
                data["tl"] = tl
        l2n = l2_name[l2k] if l2k and len(sd["l2"]) > 1 else gu   # 인기단지(실시간 검색)용: 지역 2단계 이름
        pm = {"p": f"{sdir}/{APT_DIR}/{k}.html", "n": a["n"], "s": sdir, "g": l2n, "d": a["u"], "y": year, "h": info.get("hh", 0), "k": 0}
        ctx = {"pm": pm, "ranks": ranks.get(k, []), "sido_short": sd["short"], "name": a["n"], "loc": loc, "loc2": " ".join(x for x in (gu, a["u"]) if x), "poi": pcache.get(k) if (pcache.get(k) or {}).get("x") else None, "fav": [a["n"], f"{sd['short']} {gu} {a['u']}".strip(), f"{sdir}/{APT_DIR}/{k}.html"], "jibun": a["j"], "road": info.get("road", ""), "info": info,
               "meta": " · ".join(x for x in ("" if (info.get("kind") or "아파트") == "아파트" else info["kind"], built, age) if x),
               "crumbs": crumbs, "root": "../../", "data": data, "today": now.strftime("%Y%m%d"),
               "map_q": f"{sd['short']} {gu} {a['u']} {a['n']}".replace("  ", " "),
               "page_url": f"{site_url}/{sdir}/{APT_DIR}/{k}.html",
               "seo_title": f"{a['n']} 실거래가 ({sd['short']} {gu} {a['u']}) | 옆집얼마",
               "seo_desc": f"{sd['short']} {gu} {a['u']} {a['n']} 아파트 매매·전월세 실거래가와 시세 흐름 — 2006년부터 평형별 거래 내역, 신고가, 거래량 | 옆집얼마"}
        r2 = os.environ.get("R2_OUT")   # R2 를 쓰면 거래 데이터는 따로 JSON 으로 (페이지는 가볍게)
        if r2:
            jd = os.path.join(r2, sdir, APT_DIR)
            os.makedirs(jd, exist_ok=True)
            with open(os.path.join(jd, f"{k}.json"), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            ctx["data"] = None
            ctx["data_url"] = f"{os.environ.get('R2_PUBLIC', 'https://data.nextdoorprice.com')}/{sdir}/{APT_DIR}/{k}.json?v={ctx['today']}"
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
    al = {k: (to, apts[to]["n"]) for k, to in alias.items() if to in apts}
    al.update({to: (to, apts[to]["n"]) for k, to in alias.items() if to in apts})   # 대표 단지도 합친 이름으로
    return done, search, urls, moved, al
