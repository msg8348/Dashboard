"""전국 아파트 실거래 대시보드 생성기.

    python national.py            # 국토부 실거래 갱신(가능한 만큼) → site/ 아래 전국·시도·시군구 페이지 생성
    python national.py --no-fetch # 저장된 데이터로 페이지만 생성

저장 위치 (STORE_DIR, 기본 store/ — 워크플로에서 'data' 브랜치로 보관)
    store/{sale,pre,rent}/{시도코드}.json.gz   시도별 13개월 실거래 (매매·분양권·전월세)
    store/indicators.json                      분기마다 고정하는 시도별 지표단지
    store/regions.json                         지역 목록 (공동주택 단지 목록 API 확인 결과)

수집 순서: ① 어제까지 받았던 지역의 최근 3개월(신규 공개분 판별) ② 처음 받는 지역의 최근 3개월 ③ 나머지 과거 달.
호출 한도에 걸리면 그 출처는 멈추고 받은 데까지 저장한 뒤 다음 실행에서 이어 받는다.
"""
import argparse
import gzip
import json
import os
import re
import shutil
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from jinja2 import Environment, FileSystemLoader

import Dashboard as D
import applyhome
import complex as CX
import presale as PS
import kapt
import regions

STORE = os.environ.get("STORE_DIR", "store")
SITE = "site"
SITE_URL = "https://nextdoorprice.com"
regions.PATH = os.path.join(STORE, "regions.json")
IND_PATH = os.path.join(STORE, "indicators.json")
HIST = os.environ.get("HIST_DIR", "hist")
BUSAN = "26"
WORKERS = int(os.environ.get("FETCH_WORKERS", "8"))   # 동시 요청 수
APT_SIDOS = {"26", "11"}   # 단지 페이지를 연 시도 (부산 · 서울) — 과거 수집이 끝난 시도부터


# ---------------------------------------------------------------- 저장소
def dbpath(src, key):
    return os.path.join(STORE, src, f"{key}.json.gz")


def load_db(src, key):
    p = dbpath(src, key)
    if os.path.exists(p):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return json.load(f)
    return {"version": 3, "trades": [], "fetched": []}


def save_db(src, key, db):
    os.makedirs(os.path.dirname(dbpath(src, key)), exist_ok=True)
    with gzip.open(dbpath(src, key), "wt", encoding="utf-8", compresslevel=6) as f:
        json.dump(db, f, ensure_ascii=False, separators=(",", ":"))


def migrate_busan():
    """예전 부산 전용 DB(data/*.json)를 시도별 저장소로 옮김 (최초 1회)."""
    if os.path.exists(dbpath("sale", BUSAN)) or not os.path.exists(D.SOURCES["sale"][1]):
        return
    for src in D.SOURCES:
        path = D.SOURCES[src][1]
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
        for t in old["trades"]:
            t["c"] = D.BUSAN_LAWD_CD.get(t["d"], "")
        old["fetched"] = [f"{D.BUSAN_LAWD_CD[x.split('|')[0]]}|{x.split('|')[1]}" for x in old.get("fetched", [])
                          if x.split("|")[0] in D.BUSAN_LAWD_CD]
        old["version"] = 3
        save_db(src, BUSAN, old)
        print(f"📦 부산 {D.SOURCES[src][2]} {len(old['trades']):,}건 이전")


# ---------------------------------------------------------------- 수집
def update(src, dbs, sidos, today, max_calls=40000, minutes=70):
    today_s = today.strftime("%Y%m%d")
    months = D.month_list(today, D.WINDOW_MONTHS)
    oldest = months[-1]
    tasks = []
    for sd in sidos:
        fetched = set(dbs[sd["key"]]["fetched"])
        for code, name in sd["codes"].items():
            for i, ym in enumerate(months):
                k = f"{code}|{ym}"
                if k in fetched:
                    if i < D.REFRESH_MONTHS:
                        tasks.append((0, sd["key"], code, name, ym))
                else:
                    tasks.append((1 if i < D.REFRESH_MONTHS else 2, sd["key"], code, name, ym))
    tasks.sort()
    groups = {}   # 시도별 {(코드, 연월): [거래]} — 필요할 때만 만든다

    def grp(key):
        if key not in groups:
            g = defaultdict(list)
            for t in dbs[key]["trades"]:
                g[(t.get("c", ""), t["dt"][:6])].append(t)
            groups[key] = g
        return groups[key]

    calls = ok = errs = streak = 0
    started = time.time()
    fetched_sets = {k: set(db["fetched"]) for k, db in dbs.items()}
    stop, i = False, 0
    with ThreadPoolExecutor(WORKERS) as ex:   # 여러 지역을 동시에 요청 (순서대로 처리)
        while i < len(tasks) and not stop:
            if calls >= max_calls or time.time() - started > minutes * 60:
                print(f"⏸️ 시간·호출 한도 — 남은 {len(tasks) - i}건은 다음 실행에서 이어 받음")
                break
            batch = tasks[i:i + WORKERS * 2]
            i += len(batch)
            futs = [(t, ex.submit(D.fetch_month, src, t[3], t[2], t[4])) for t in batch]
            for (phase, key, code, name, ym), fut in futs:
                calls += 1
                try:
                    fresh = fut.result()
                except D.QuotaError as e:
                    if not stop:
                        print(f"⛔ {e} — 남은 분량은 다음 실행에서 이어 받음")
                    stop = True
                    continue
                except D.FetchError as e:
                    errs += 1
                    streak += 1
                    if errs <= 5:
                        print("⚠️", e)
                    if streak >= 30:
                        print("⛔ 연속 실패가 많아 이 출처는 중단")
                        stop = True
                    continue
                streak = 0
                ok += 1
                db = dbs[key]
                g = grp(key)
                k = f"{code}|{ym}"
                known = k in fetched_sets[key]
                old_ids = {t["id"]: t for t in g.get((code, ym), [])}
                for t in fresh:
                    t["c"] = code
                    prev = old_ids.get(t["id"])
                    t["seen"] = prev["seen"] if prev else (today_s if known else "")
                g[(code, ym)] = fresh
                if not known:
                    db["fetched"].append(k)
                    fetched_sets[key].add(k)
    for key, g in groups.items():
        dbs[key]["trades"] = [t for (c, ym), ts in g.items() if ym >= oldest for t in ts]
    for db in dbs.values():
        db["fetched"] = sorted(x for x in set(db["fetched"]) if x.split("|")[1] >= oldest)
    total = sum(len(sd["codes"]) for sd in sidos) * len(months)
    have = sum(len(db["fetched"]) for db in dbs.values())
    print(f"✅ {D.SOURCES[src][2]}: 호출 {calls}회(성공 {ok}, 실패 {errs}) · 지역·월 {have}/{total} · {time.time() - started:.0f}초")


# ---------------------------------------------------------------- 지표단지
def quarter(today):
    return f"{today.year}Q{(today.month - 1) // 3 + 1}"


def kapt_rows_by_l2(sd):
    """K-apt 단지(아파트·주상복합)를 레벨2 로 나눔."""
    idx = {}
    for l in sd["l2"]:
        idx[D.normalize(l["name"])] = l["key"]
        for n in l["codes"].values():
            idx[D.normalize(n)] = l["key"]
            idx[D.normalize(n.split()[-1]) if not sd["metro"] else D.normalize(n)] = l["key"]
    # 일반구가 생긴 시 (예: K-apt '화성동탄구' → 화성시)
    stems = [(D.normalize(l["name"][:-1]), l["key"]) for l in sd["l2"] if l["name"].endswith("시") and not sd["metro"]]
    out = defaultdict(list)
    for r in kapt.load():
        if r["sido"] != sd["sido"] or not kapt.is_apartment(r):
            continue
        s = D.normalize(r["sigungu"])
        if not s and len(sd["l2"]) == 1:   # 세종처럼 시군구가 없는 곳
            out[sd["l2"][0]["key"]].append(r)
            continue
        k = idx.get(s) or next((k for st, k in stems if s.startswith(st)), None)
        if k:
            out[k].append(r)
    return out


def ckey(name):
    """단지 비교용 이름: 표기 차이(에스/S, 이편한/e편한, '아파트')와 'n단지' 를 없앤 이름 — 1·2단지는 한 단지로 본다."""
    n = D.normalize(name).lower()
    for x, y in (("에스", "s"), ("이편한", "e편한"), ("아이파크", "ipark"), ("아파트", "")):
        n = n.replace(x, y)
    return re.sub(r"(제?\d+단지|\d+블럭|[a-z]\d+bl)$", "", n) or n


def match_households(key, rows):
    """K-apt 세대수: 같은 이름 단지 합계, 없으면 이름이 포함되는 단지 중 가장 비슷한 곳."""
    same = [r for r in rows if ckey(r["name"]) == key]
    if same:
        return sum(r["households"] for r in same)
    best = None
    for r in rows:
        m = ckey(r["name"])
        if key and m and (key in m or m in key):
            score = -abs(len(m) - len(key))
            if best is None or score > best[0]:
                best = (score, r)
    return best[1]["households"] if best else 0


def pick_indicators(sd, sale, today, kapt_l2, l2_of, complete):
    """레벨2 마다 지표단지 1곳 (분기 고정). complete: 13개월을 다 받은 레벨2 키 집합 — 이곳만 분기 값으로 저장."""
    st = {}
    if os.path.exists(IND_PATH):
        with open(IND_PATH, encoding="utf-8") as f:
            st = json.load(f)
    q = quarter(today)
    if st.get("quarter") != q:
        st = {"quarter": q, "picks": {}}
    saved = st["picks"].setdefault(sd["key"], {})
    d1 = (today - timedelta(days=365)).strftime("%Y%m%d")
    by = defaultdict(list)
    for t in sale:
        if t["dt"] > d1:
            by[l2_of.get(t.get("c"), "")].append(t)
    picks = {}
    for l in sd["l2"]:
        if l["key"] in saved:
            picks[l["key"]] = saved[l["key"]]
            continue
        ts = by.get(l["key"], [])
        if not ts:
            continue
        cx = defaultdict(list)
        for t in ts:
            cx[ckey(t["n"])].append(t)

        def summary(k, lst):
            names = Counter(t["n"] for t in lst)
            p84 = [t["p"] for t in lst if 78 <= t["a"] <= 88]
            name = names.most_common(1)[0][0]
            if len(names) > 1:   # 1·2단지 등을 묶은 경우 '(1단지)' 같은 꼬리를 뗀 이름으로 표시
                name = re.sub(r"\s*\(?제?\d+단지\)?$", "", name) or name
            return {"key": k, "names": sorted(names), "name": name,
                    "n84": len(p84), "avg84": round(sum(p84) / len(p84)) if p84 else 0, "n": len(lst)}
        rows = [summary(k, lst) for k, lst in cx.items()]
        with84 = [r for r in rows if r["n84"]]
        if with84:
            top5 = sorted(with84, key=lambda r: -r["avg84"])[:5]
            p = max(top5, key=lambda r: (r["n84"], r["avg84"]))
            p["rule"] = ""
        else:
            p = max(rows, key=lambda r: r["n"])
            p["rule"] = "거래 최다 대체"
        p["households"] = match_households(p["key"], kapt_l2.get(l["key"], []))
        picks[l["key"]] = p
        if l["key"] in complete:
            saved[l["key"]] = p
    os.makedirs(os.path.dirname(IND_PATH), exist_ok=True)
    with open(IND_PATH, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    return picks


# ---------------------------------------------------------------- 페이지
def subset(dbs, codes):
    return {src: {"trades": [t for t in db["trades"] if t.get("c") in codes], "highs3": db.get("highs3", {})}
            for src, db in dbs.items()}


def pre_history(key):
    """과거 분양권(2020년~, history 브랜치) → {(시군구코드, 단지키): [전용면적, ...]}"""
    p = os.path.join(HIST, f"pre_{key}.json.gz")
    out = defaultdict(list)
    if os.path.exists(p):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            db = json.load(f)
        for a in db.get("apts", {}).values():
            out[(a["c"], ckey(a["n"]))] += [(r[4], int(r[0])) for r in a["t"]]   # (전용면적, 계약일)
    return out


def same_type(area, ref):
    """84·59 는 타입으로, 기타는 전용면적 ±1.5㎡ 로 같은 평형 판단."""
    t = D.area_type(ref)
    return D.area_type(area) == t if t != "기타" else abs(area - ref) <= 1.5


def hi_type(a):
    """최고가 평형: 59 · 74(전용 70~77㎡) · 84 — 단지 페이지 매매가 순위와 같은 기준, 나머지 0(기타)."""
    ai = int(a)
    return 59 if ai == 59 else 74 if 70 <= ai <= 77 else 84 if ai == 84 else 0


def hi_build(sd, sdir, sdb, cinfo, l2_of, l2_name):
    """site/hi/{시도}/{연도}.json — {"m": [[단지키, 이름, 구·군, 동, 입주년, 분양권]], "t": [[단지번호, 종류(0 매매·1 분양권·2 전세), 평형, 월, 금액, 층, 계약일, 면적]]}
    (단지·종류·평형·월마다 최고 거래 1건). site/hi/{시도}.json = {"y": [연도...], "g": [구·군...], "d": {구·군: [동...]}}.
    매매는 과거 수집(2006~)+최근 13개월, 분양권은 과거(2020~)+최근, 전세는 최근 13개월."""
    l2 = lambda c, d="": l2_name.get(l2_of.get(c), (d or "").split()[-1] if d else "")
    meta, best = {}, {}

    def put(k, m, kind, t_dt, p, f, a):
        y, mo = str(t_dt)[:4], int(str(t_dt)[4:6] or 0)
        if not y.isdigit() or not mo or not p:
            return
        if k not in meta:
            meta[k] = m
        kk = (y, k, kind, hi_type(a), mo)
        if kk not in best or p > best[kk][0]:
            best[kk] = (p, str(f), int(str(t_dt)[6:8] or 0), round(a, 1))

    def sale_key(t):
        if t.get("s") in D.APT_ALIAS:
            return f"{sdir}/apt/{D.APT_ALIAS[t['s']][0]}.html"
        return f"{sdir}/apt/{t['s']}.html" if t.get("s") and t["s"] in D.APT_PAGES else f"{t['n']}|{l2(t.get('c'), t.get('d'))}"
    for t in sdb["sale"]["trades"]:
        hh, ap = cinfo(t)
        yr = int(ap[:4]) if ap and ap[:4].isdigit() else (int(t["by"]) if str(t.get("by", "")).isdigit() else 0)
        put(sale_key(t), [D.APT_ALIAS.get(t.get("s"), (0, t["n"]))[1], l2(t.get("c"), t.get("d")), t.get("u", ""), yr, 0], 0, t["dt"], t["p"], t.get("f", ""), t["a"])
    for t in sdb["rent"]["trades"]:
        if t.get("m"):
            continue   # 전세만 (월세 제외)
        hh, ap = cinfo(t)
        yr = int(ap[:4]) if ap and ap[:4].isdigit() else 0
        put(sale_key(t), [D.APT_ALIAS.get(t.get("s"), (0, t["n"]))[1], l2(t.get("c"), t.get("d")), t.get("u", ""), yr, 0], 2, t["dt"], t["p"], t.get("f", ""), t["a"])
    for t in sdb["pre"]["trades"]:
        hh, mv, extra = cinfo(dict(t, src="pre"))
        k = f"{sdir}/{extra['h']}.html" if extra.get("h") else f"{t['n']}|{l2(t.get('c'), t.get('d'))}"
        put(k, [t["n"], l2(t.get("c"), t.get("d")), t.get("u", ""), int(str(mv)[:4]) if mv else 0, 1], 1, t["dt"], t["p"], t.get("f", ""), t["a"])
    # 과거 수집분 (최근 13개월 창 이전)
    oldest = min((str(t["dt"])[:6] for t in sdb["sale"]["trades"]), default="999999")
    for src, kind in (("", 0), ("pre_", 1)):
        pth = os.path.join(HIST, f"{src}{sd['key']}.json.gz")
        if not os.path.exists(pth):
            continue
        with gzip.open(pth, "rt", encoding="utf-8") as f:
            apts = json.load(f).get("apts", {})
        for ak, a in apts.items():
            code = a.get("c", "")
            if kind == 0:
                k = (f"{sdir}/apt/{D.APT_ALIAS[ak][0]}.html" if ak in D.APT_ALIAS else
                     f"{sdir}/apt/{ak}.html" if ak in D.APT_PAGES else f"{a['n']}|{l2(code)}")
                m = [D.APT_ALIAS.get(ak, (0, a["n"]))[1], l2(code), a.get("u", ""), int(a["by"]) if str(a.get("by", "")).isdigit() else 0, 0]
            else:
                k = f"{a['n']}|{l2(code)}"
                m = [a["n"], l2(code), a.get("u", ""), 0, 1]
            for x in a["t"]:
                if str(x[0])[:6] < oldest:
                    put(k, m, kind, x[0], x[1], x[2], x[4])
    base = os.path.join(SITE, "hi", sdir)
    os.makedirs(base, exist_ok=True)
    years = sorted({kk[0] for kk in best})
    for y in years:
        keys, idx, rows = [], {}, []
        for (yy, k, kind, ty, mo), (p, f, dd, a) in best.items():
            if yy != y:
                continue
            if k not in idx:
                idx[k] = len(keys)
                keys.append([k] + meta[k])
            rows.append([idx[k], kind, ty, mo, p, f, dd, a])
        with open(os.path.join(base, f"{y}.json"), "w", encoding="utf-8") as f:
            json.dump({"m": keys, "t": rows}, f, ensure_ascii=False, separators=(",", ":"))
    dongs = defaultdict(set)
    for m in meta.values():
        if m[1] and m[2]:
            dongs[m[1]].add(m[2])
    with open(os.path.join(SITE, "hi", f"{sdir}.json"), "w", encoding="utf-8") as f:
        json.dump({"y": years, "g": [l["name"] for l in sd["l2"]] if len(sd["l2"]) > 1 else [],
                   "d": {g: sorted(v) for g, v in dongs.items()}}, f, ensure_ascii=False, separators=(",", ":"))


def pop_periods(today):
    """인기단지 기간: (키, 이름, 시작, 끝, 기준) — 주는 월요일 시작, 기준 'seen'=공개일 · 'dt'=계약일."""
    mon = today - timedelta(days=today.weekday())
    f = lambda d: d.strftime("%Y%m%d")
    m1 = today.replace(day=1)
    pm_end = m1 - timedelta(days=1)
    return [("tw", "이번주", f(mon), f(today), "seen"), ("lw", "지난주", f(mon - timedelta(days=7)), f(mon - timedelta(days=1)), "seen"),
            ("tm", "이번달", f(m1), f(today), "dt"), ("lm", "지난달", f(pm_end.replace(day=1)), f(pm_end), "dt"),
            ("ty", "올해", f(today.replace(month=1, day=1)), f(today), "dt")]


def pop_build(sd, sdir, sdb, cinfo, l2_of, l2_name):
    """site/pop/{시도}.json — {"p": 기간 [[키, 이름, 시작, 끝]], "m": {단지키: [이름, 구·군, 동, 입주년, 세대수, 분양권]},
    "r": {기간키: {"": [[단지키, 건수]...], 구·군: [...]}} (상위 10)}. 단지키 = 페이지 주소(시도/apt/…) 또는 '이름|구·군'."""
    today = datetime.now(D.KST)
    periods = pop_periods(today)
    meta, rows = {}, []
    for src in ("sale",):   # 많이 산 단지: 매매만 (분양권 제외)
        for t in sdb[src]["trades"]:
            l2 = l2_name.get(l2_of.get(t.get("c")), (t.get("d") or "").split()[-1] if t.get("d") else "")
            if src == "sale":
                hh, ap = cinfo(t)
                k = (f"{sdir}/apt/{D.APT_ALIAS[t['s']][0]}.html" if t.get("s") in D.APT_ALIAS else
                     f"{sdir}/apt/{t['s']}.html" if t.get("s") and t["s"] in D.APT_PAGES else f"{t['n']}|{l2}")
                yr = int(ap[:4]) if ap and ap[:4].isdigit() else (int(t["by"]) if str(t.get("by", "")).isdigit() else 0)
            else:
                hh, mv, extra = cinfo(dict(t, src="pre"))
                k = f"{sdir}/{extra['h']}.html" if extra.get("h") else f"{t['n']}|{l2}"
                yr = int(str(mv)[:4]) if mv else 0
            if k not in meta:
                meta[k] = [D.APT_ALIAS.get(t.get("s"), (0, t["n"]))[1], l2, t.get("u", ""), yr, hh or 0, 1 if src == "pre" else 0]
            rows.append((k, l2, str(t.get("dt", "")), t.get("seen") or ""))
    out = {"p": [[pk, nm, a, b] for pk, nm, a, b, _ in periods], "m": {}, "r": {}}
    for pk, nm, a, b, basis in periods:
        by = defaultdict(lambda: defaultdict(int))
        for k, l2, dt, seen in rows:
            d = seen if basis == "seen" else dt
            if a <= d <= b:
                by[""][k] += 1
                by[l2][k] += 1
        out["r"][pk] = {g: sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:10] for g, c in by.items()}
    used = {k for per in out["r"].values() for lst in per.values() for k, _ in lst}
    out["m"] = {k: meta[k] for k in used}
    out["g"] = [l["name"] for l in sd["l2"]] if len(sd["l2"]) > 1 else []
    os.makedirs(os.path.join(SITE, "pop"), exist_ok=True)
    with open(os.path.join(SITE, "pop", f"{sdir}.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))


def match_house(houses, sd, t):
    """분양권 거래 → 청약홈 분양 단지 (같은 시군구 + 단지명)."""
    gu = t["d"].split()[-1]
    k = ckey(t["n"])
    best = None
    for h in houses:
        if gu not in h["addr"] or (sd["short"][:2] not in h["addr"] and sd["short"] != "광주전남"):
            continue
        hk = ckey(h["name"])
        if hk == k or (k and hk and (k in hk or hk in k)):
            score = (hk == k, -abs(len(hk) - len(k)), h["id"])
            if best is None or score > best[0]:
                best = (score, h)
    return best[1] if best else None


def subset_asof(dbs, codes, day):
    """그날(day, YYYYMMDD)까지 공개된 거래만 + 그날의 신고가 기준값 — 지난 날짜 화면용."""
    out = {}
    for src, db in dbs.items():
        out[src] = {"trades": [t for t in db["trades"] if t.get("c") in codes and (t.get("seen") or "") <= day],
                    "highs3": (db.get("highs3_by") or {}).get(day, {})}
    return out


def date_opts(days, cur, fname, archived):
    """날짜 선택 목록 [(라벨, 주소, 선택)] — 오늘 페이지는 ./, 지난 날짜는 ./d{날짜}/ 폴더."""
    out = []
    for i, d in enumerate(days):
        lbl = f"{d[2:4]}.{d[4:6]}.{d[6:]}"
        if i == 0:
            href = f"../{fname}" if archived else fname
        else:
            href = f"../d{d}/{fname}" if archived else f"d{d}/{fname}"
        out.append((lbl, href, d == cur))
    return out


def avg84(sale, today, days=30):
    d0 = (today - timedelta(days=days)).strftime("%Y%m%d")
    p = [t["p"] for t in sale if t["dt"] > d0 and 78 <= t["a"] <= 88]
    if not p:
        return "-"
    from decimal import Decimal, ROUND_HALF_UP   # 만원 → 억, 소수 둘째 자리에서 반올림 (예: 12.79억 → 12.8억)
    eok = (Decimal(sum(p)) / len(p) / 10000).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{eok}억"


def redirect(old, new):
    """예전 주소(/r/26/…)로 들어오면 새 주소로 이동하는 작은 페이지."""
    path = os.path.join(SITE, old)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    up = "../" * old.count("/")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url={up}{new}">'
                f'<link rel="canonical" href="{up}{new}"><script>location.replace("{up}{new}")</script>')


PROBE_CODES = ["11680", "41135", "26350", "11650"]   # 강남구 · 성남 분당구 · 해운대구 · 서초구


def probe(dbs, sidos, today):
    """국토부에 새 거래가 공개됐는지 몇 곳만 빠르게 확인 (이번 달·지난달 매매 건수 비교)."""
    names = {c: n for sd in sidos for c, n in sd["codes"].items()}
    months = D.month_list(today, 2)
    for code in PROBE_CODES:
        if code not in names:
            continue
        key = code[:2]
        for ym in months:
            try:
                fresh = D.fetch_month("sale", names[code], code, ym)
            except D.FetchError as e:
                print("⚠️ 확인 실패 — 전체 수집 진행:", e)
                return True
            have = sum(1 for t in dbs["sale"].get(key, {}).get("trades", []) if t.get("c") == code and t["dt"][:6] == ym)
            if len(fresh) != have:
                print(f"🔔 새 공개 확인: {names[code]} {ym} {have}→{len(fresh)}건 — 전체 수집 시작")
                return True
    print("💤 아직 새로 공개된 거래 없음 — 이번 실행은 건너뜀")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--max-calls", type=int, default=40000)
    ap.add_argument("--minutes", type=float, default=70, help="출처별 수집 시간 한도(분)")
    ap.add_argument("--probe", action="store_true", help="새 공개가 있을 때만 수집·배포 (예약 실행용)")
    ap.add_argument("--only", default="", help="시도 코드만 (예: 26,41) — 시험용")
    args = ap.parse_args()
    now = datetime.now(D.KST)

    migrate_busan()
    sidos = regions.build(regions.load(now))
    if args.only:
        sidos = [s for s in sidos if s["key"] in args.only.split(",")]
    print(f"🗺️ {len(sidos)}개 시도 · {sum(len(s['codes']) for s in sidos)}개 시군구")

    dbs = {src: {sd["key"]: load_db(src, sd["key"]) for sd in sidos} for src in D.SOURCES}
    if args.probe and D.MOLIT_API_KEY and not args.no_fetch and not probe(dbs, sidos, now):
        open("SKIP_DEPLOY", "w").close()
        return
    if D.MOLIT_API_KEY and not args.no_fetch:
        for src in D.SOURCES:
            update(src, dbs[src], sidos, now, args.max_calls, args.minutes)
    elif not D.MOLIT_API_KEY:
        print("⚠️ MOLIT_API_KEY 가 없어 저장된 데이터로만 만듭니다.")

    # 오늘 새로 공개된 거래가 아직 없으면(국토부 공개 전 새벽 등) 마지막으로 신규 거래가 잡힌 날 기준으로 표시
    fallback = False
    last = max((t.get("seen") or "" for src in ("sale", "rent") for db in dbs[src].values() for t in db["trades"]), default="")
    if last and last < now.strftime("%Y%m%d"):
        now = now.replace(year=int(last[:4]), month=int(last[4:6]), day=int(last[6:]))
        fallback = True
        print(f"🗓️ 오늘 신규 공개 거래가 아직 없어 {last} 기준으로 표시")
        for src in ("sale", "rent"):   # 그날 기준으로 저장해 둔 신고가 기준값 사용
            for key, db in dbs[src].items():
                prev = (db.get("highs3_by") or {}).get(last)
                if prev is None and key == BUSAN and os.path.exists(D.SOURCES[src][1]):   # 예전 부산 전용 DB(11.13 기준)
                    with open(D.SOURCES[src][1], encoding="utf-8") as f:
                        prev = json.load(f).get("highs3")
                db["highs3"] = prev or {}
    # 부산 11.13 신고가 기준값: 날짜별 보관 이전이라 예전 부산 전용 DB 값 사용
    for src in ("sale", "rent"):
        db = dbs[src].get(BUSAN)
        if db is not None and "20261113" not in (db.get("highs3_by") or {}) and os.path.exists(D.SOURCES[src][1]):
            with open(D.SOURCES[src][1], encoding="utf-8") as f:
                legacy = json.load(f).get("highs3")
            if legacy:
                db.setdefault("highs3_by", {})["20261113"] = legacy
    houses = applyhome.load(os.path.join(STORE, "applyhome.json"), D.MOLIT_API_KEY, now)
    today_s = now.strftime("%Y%m%d")
    d7 = (now - timedelta(days=6)).strftime("%Y%m%d")
    seen_days = {t.get("seen") for src in ("sale", "rent") for db in dbs[src].values() for t in db["trades"]}
    days = [today_s] + sorted((d for d in seen_days if d and d7 <= d < today_s), reverse=True)
    print(f"🗓️ 날짜 선택: {', '.join(days)}")
    env = Environment(loader=FileSystemLoader("templates"), autoescape=True)
    tpl = env.get_template("report_template.html")
    shutil.rmtree(SITE, ignore_errors=True)
    if os.path.isdir("static"):   # 아이콘·매니페스트
        shutil.copytree("static", SITE)
    months = D.month_list(now, D.WINDOW_MONTHS)
    urls = []
    home = []
    act_nat, act_sidos = {"s": [], "g": []}, []   # 홈 '거래활발도'
    bud_sidos = []   # 나의 예산
    sub_sidos = []   # 청약단지
    # 알림 서버(cloudflare/push)가 읽는 오늘의 알림 재료: 관심단지별 신규 거래 문구, 지역별 요약 숫자
    push = {"date": now.strftime("%Y%m%d"), "new": not fallback, "apts": {}, "regions": {}}

    def push_msg(c):
        kind = {"sale": "매매", "pre": "분양권"}.get(c["k"], "월세" if c.get("m") else "전세")
        price = D.fmt_short(c["p"]) + (f"/{c['m']:,}" if c.get("m") else "")
        fl = f" {c['f']}층" if str(c.get("f", "")).lstrip("-").isdigit() else ""
        return f"{kind} {c.get('tl') or str(round(c['a'])) + '㎡'} {price}{fl}" + (" 신고가" if c.get("up") else "")
    search = []
    for sd in sidos:
        key = sd["key"]
        sdb = {src: dbs[src][key] for src in D.SOURCES}
        fetched = set(sdb["sale"]["fetched"])
        l2_of = {c: l["key"] for l in sd["l2"] for c in l["codes"]}
        l2_name = {l["key"]: l["name"] for l in sd["l2"]}
        for t in sdb["sale"]["trades"]:
            t["l2"] = l2_name.get(l2_of.get(t.get("c")), t["d"])
        ready = bool(fetched)
        l2_word = "구·군" if sd["metro"] else "시·군"
        sdir = regions.sido_slug(sd["short"])        # 주소: /busan/ , /busan/haeundae-gu.html
        l2slug, used = {}, set()
        for l in sd["l2"]:
            sl = regions.slug(l["name"]) or l["key"]
            if sl in used or sl == "index":
                sl = f"{sl}-{l['key']}"
            used.add(sl)
            l2slug[l["key"]] = sl
        os.makedirs(os.path.join(SITE, sdir), exist_ok=True)
        if key in APT_SIDOS:   # 단지 페이지 (과거 실거래가 있는 시도)
            pby = PS.group(sd, sdb, HIST, months[-1], houses, match_house)
            done, srch, aurls, moved, alias = CX.build(sd, sdir, sdb, HIST, months[-1], now, env, SITE, l2slug, l2_of, ckey, SITE_URL, STORE,
                                                pre=PS.moving(pby, houses, now), houses=houses)
            D.APT_PAGES |= done
            D.APT_ALIAS.update(alias)
            D.PRE_MOVED.update(moved)
            search += srch
            urls += aurls
            done, srch, aurls = PS.build(sd, sdir, sdb, HIST, months[-1], now, env, SITE, l2slug, l2_of, houses, match_house, STORE, SITE_URL,
                                         by=pby, moved=moved)
            D.PRE_PAGES |= done
            search += srch
            urls += aurls
        base = {"date_label": now.strftime("%y.%m.%d"), "date_full": now.strftime("%Y%m%d"), "notices": [],
                "l2_word": l2_word, "home_href": "../index.html", "root": "../", "site_url": SITE_URL,
                "l2opts": sorted([(l["name"], f"{l2slug[l['key']]}.html") for l in sd["l2"]]) if len(sd["l2"]) > 1 else [],   # 가나다순
                "dates": date_opts(days, today_s, "index.html", False), "apt_base": f"../{sdir}/"}
        if not ready:
            base["notices"].append("이 지역은 실거래 데이터를 수집하고 있습니다. 며칠 안에 채워집니다.")
        # --- 레벨1
        kapt_l2 = kapt_rows_by_l2(sd)
        ccache = {}

        pre_hist = pre_history(key)
        pre_now = defaultdict(list)
        for t in sdb["pre"]["trades"]:
            pre_now[(t.get("c"), ckey(t["n"]))].append((t["a"], int(t["dt"])))
        pcache = {}

        def cinfo(t, kapt_l2=kapt_l2, l2_of=l2_of, ccache=ccache, sd=sd, pre_hist=pre_hist, pre_now=pre_now, pcache=pcache):
            """실거래 카드용 단지 세대수·사용승인일 (K-apt). 분양권은 청약홈 입주예정월·공급세대수 + 분양 이후 누적 거래."""
            if t.get("src") == "pre":
                ck = (t.get("c"), ckey(t["n"]), D.area_type(t["a"]) if D.area_type(t["a"]) != "기타" else round(t["a"]))
                if ck not in pcache:
                    areas = pre_hist.get(ck[:2], []) + pre_now.get(ck[:2], [])
                    h = match_house(houses, sd, t)
                    since = int(re.sub(r"\D", "", (h or {}).get("pbl") or "")[:8] or 0)   # 모집공고 이전 거래는 같은 이름의 옛 단지
                    pc = sum(1 for a, d in areas if same_type(a, t["a"]) and d >= since)
                    extra = {"pc": pc}
                    if h and h["id"] in D.PRE_PAGES:
                        extra["h"] = f"pre/{h['id']}"   # 분양권 페이지
                    elif h and h["id"] in D.PRE_MOVED:
                        extra["h"] = f"apt/{D.PRE_MOVED[h['id']]}"   # 입주 후 매매 단지로 옮겨 간 곳
                    if h:
                        sup = sum(n for a, n, *_ in h["types"] if same_type(a, t["a"]))
                        if sup:
                            extra["sup"] = sup
                        pcache[ck] = (h["total"] or None, h["mvn"] or None, extra)
                    else:
                        pcache[ck] = (None, None, extra)
                return pcache[ck]
            k2 = l2_of.get(t.get("c"))
            ck = (k2, ckey(t["n"]))
            if ck not in ccache:
                rows = kapt_l2.get(k2, [])
                same = [r for r in rows if ckey(r["name"]) == ck[1]]
                if not same:
                    same = [r for r in rows if ck[1] and (ck[1] in ckey(r["name"]) or ckey(r["name"]) in ck[1])][:1]
                ccache[ck] = ((sum(r["households"] for r in same) or None),
                              (min((r.get("approval_date") or "9") for r in same) if same else None)) if same else (None, None)
                if ccache[ck][1] == "9":
                    ccache[ck] = (ccache[ck][0], None)
            return ccache[ck]

        tlc = {}

        def tlabel(t, sd=sd, tlc=tlc):
            """청약홈 단지(같은 시군구·같은 이름)의 주택형 전용면적과 거래 면적이 같으면 약식표기 (84A …)."""
            k = (t.get("c"), t["n"])
            if k not in tlc:
                h = match_house(houses, sd, t)
                if h and t.get("src") != "pre" and ckey(h["name"]) != ckey(t["n"]):
                    h = None   # 매매·전월세는 이름이 정확히 같을 때만 (같은 이름의 옛 단지 오인 방지)
                tlc[k] = [x for x in (h or {}).get("types", []) if len(x) >= 5]
            for x in tlc[k]:
                if abs(x[4] - t["a"]) < 0.006:
                    return x[2] if x[2][-1].isalpha() else ""
            return ""
        D.TYPE_LABEL = tlabel
        sale_ctx, rent_ctx, highs_s, highs_r = D.build_trades(subset(sdb, set(sd["codes"])), now, cinfo)
        favc = [c for c in sale_ctx["cards"] if c.get("h")]   # 관심단지 화면용 (최근 7일, 단지 페이지 있는 거래)
        if not fallback:   # 날짜별 기준값도 보관 (최근 3일) — 신규 공개가 없는 날 전날 기준으로 다시 보여줄 때 사용
            for src, h in (("sale", highs_s), ("rent", highs_r)):
                by = sdb[src].setdefault("highs3_by", {})
                by[now.strftime("%Y%m%d")] = h
                for d in sorted(by)[:-8]:
                    by.pop(d)
            sdb["sale"]["highs3"], sdb["rent"]["highs3"] = highs_s, highs_r
        l2_hh = {l2_name[k]: sum(r["households"] for r in rows) for k, rows in kapt_l2.items()}
        if key == BUSAN:
            ind_args = (l2_hh, D.INDICATOR_COMPLEXES, "d", [l["name"] for l in sd["l2"]])
            ind = D.build_indicator(sdb["sale"]["trades"], now, *ind_args)
            rule = "부산 지표단지 21곳 (직접 지정)"
        else:
            complete = {l["key"] for l in sd["l2"] if all(f"{c}|{ym}" in fetched for c in l["codes"] for ym in months)}
            picks = pick_indicators(sd, sdb["sale"]["trades"], now, kapt_l2, l2_of, complete)
            cx = {l2_name[k]: [{"name": p["name"], "households": p["households"],
                                "keywords": p.get("names") or [p["name"]], "exact": True, "avg84": D.fmt_short(p["avg84"]) if p["avg84"] else "",
                                "rule": p.get("rule", "")}] for k, p in picks.items()}
            ind_args = (l2_hh, cx, "l2", [l["name"] for l in sd["l2"]])
            ind = D.build_indicator(sdb["sale"]["trades"], now, *ind_args)
            rule = f"{l2_word}별 최근 1년 84타입 평균거래가 상위 5위 안에서 거래량 최다 단지 · 84타입 거래가 없으면 거래 최다 단지 · {quarter(now)} 고정"
        ctx = dict(base, sale=sale_ctx, rent=rent_ctx, indicator=ind, has_ind=bool(ind["count"]), level=1,
                   hi={"s": sdir, "g": "", "n": sd["short"]} if key in APT_SIDOS else None,
                   region=sd["short"], region_full=sd["sido"], ind_rule=rule,
                   crumbs=[("전국", "../index.html"), (sd["short"], None)], page_url=f"{SITE_URL}/{sdir}/",
                   seo_title=f"{sd['short']} 아파트 실거래가·신고가 | 옆집얼마",
                   seo_desc=f"{sd['short']} 아파트 실거래가와 신고가를 매일 알려드립니다. {sd['sido']} {l2_word}별 신규 매매·전월세 최고가와 지표단지 거래량 — 옆집얼마")
        urls.append(f"{SITE_URL}/{sdir}/")
        redirect(f"r/{key}/index.html", f"{sdir}/index.html")   # 예전 주소 → 새 주소
        with open(os.path.join(SITE, sdir, "index.html"), "w", encoding="utf-8") as f:
            f.write(tpl.render(ctx))
        # 홈 '거래활발도': 이 시도의 지표단지·구군 조각 + 전국 순위 재료
        nm_s = "전남광주" if sd["short"] == "광주전남" else sd["short"]
        if ind["count"] or ind["gus"]:
            os.makedirs(os.path.join(SITE, "act"), exist_ok=True)
            with open(os.path.join(SITE, "act", f"{sdir}.html"), "w", encoding="utf-8") as f:
                f.write(env.get_template("_act_frag.html").render(ind=ind, region=sd["short"], l2_word=l2_word))
            act_sidos.append([nm_s, sdir])
        if ind.get("gu_rate"):
            t = ind["gu_total"]
            act_nat["s"].append({"n": nm_s, "c3": t["c3"], "c1": t["c1"], "r3": t["r3"], "r1": t["r1"], "trend": t["trend"], "change": t["change"], "h": f"{sdir}/index.html"})
            for g in ind["gus"]:
                if (g.get("hh") or 0) >= 20000:   # 작은 시군구 제외 (아파트 2만세대 이상)
                    act_nat["g"].append({"n": f"{nm_s} {g['name']}", "c3": g["c3"], "c1": g["c1"], "r3": g["r3"], "r1": g["r1"], "trend": g["trend"], "change": g["change"]})
        # --- 레벨2
        chips = []
        if len(sd["l2"]) > 1:
            for l in sd["l2"]:
                s2, r2, _, _ = D.build_trades(subset(sdb, set(l["codes"])), now, cinfo)
                c2 = dict(base, sale=s2, rent=r2, indicator=None, has_ind=False, level=2,
                          hi={"s": sdir, "g": l["name"], "n": sd["short"]} if key in APT_SIDOS else None,
                          dates=date_opts(days, today_s, f"{l2slug[l['key']]}.html", False),
                          region=l["name"], region_full=f"{sd['sido']} {l['name']}",
                          crumbs=[("전국", "../index.html"), (sd["short"], "index.html"), (l["name"], None)],
                          page_url=f"{SITE_URL}/{sdir}/{l2slug[l['key']]}.html",
                          seo_title=f"{sd['short']} {l['name']} 아파트 실거래가·신고가 | 옆집얼마",
                          seo_desc=f"{sd['short']} {l['name']} 아파트 실거래가와 신고가를 매일 알려드립니다. {l['name']} 신규 매매·전세 최고가 — 옆집얼마")
                urls.append(f"{SITE_URL}/{sdir}/{l2slug[l['key']]}.html")
                redirect(f"r/{key}/{l['key']}.html", f"{sdir}/{l2slug[l['key']]}.html")
                with open(os.path.join(SITE, sdir, f"{l2slug[l['key']]}.html"), "w", encoding="utf-8") as f:
                    f.write(tpl.render(c2))
                chips.append({"name": l["name"], "href": f"{sdir}/{l2slug[l['key']]}.html", "cnt": s2["cnt"], "high": s2["high_cnt"]})
        chips.sort(key=lambda c: c["name"])   # 지역 선택 시트도 가나다순
        for c in sale_ctx["cards"]:
            if c.get("h"):
                pa = push["apts"].setdefault(f"{sdir}/{c['h']}.html", {"n": c["n"], "t": []})
                if len(pa["t"]) < 5:
                    pa["t"].append(push_msg(c))
        nm = "전남광주" if sd["short"] == "광주전남" else sd["short"]
        push["regions"][f"{sdir}/index.html"] = {"n": nm, "c": sale_ctx["cnt"], "h": sale_ctx["high_cnt"], "r": rent_ctx["cnt"]}
        for c in chips:
            push["regions"][c["href"]] = {"n": f"{nm} {c['name']}", "c": c["cnt"], "h": c["high"]}
        import subscr, notice as NT   # 청약단지: 최근 60일 모집공고 단지 (전 시도)
        nsub = subscr.build(SITE, STORE, sd, sdir, sdb["sale"]["trades"], houses, now, D.APT_ALIAS, D.APT_PAGES,
                            NT.load(os.path.join(STORE, "notice.json")), cinfo)
        if nsub:
            sub_sidos.append(["전남광주" if sd["short"] == "광주전남" else sd["short"], sdir, nsub])
        if key in APT_SIDOS:   # 최고가: 연도별 단지·타입·월 최고 거래 (과거 데이터 있는 해부터)
            hi_build(sd, sdir, sdb, cinfo, l2_of, l2_name)
            import budget, poi as POI   # 나의 예산: 예산 맞춤 추천용 단지 목록
            budget.build(SITE, sd, sdir, sdb["sale"]["trades"], cinfo, l2_of, l2_name, D.APT_PAGES,
                         POI.load(os.path.join(STORE, "poi.json")), now, D.APT_ALIAS)
            bud_sidos.append(["전남광주" if sd["short"] == "광주전남" else sd["short"], sdir])
        if key in APT_SIDOS:   # 인기단지 '많이 산 단지': 기간·지역별 거래 많은 단지 (주 단위는 공개일, 월·연 단위는 계약일)
            pop_build(sd, sdir, sdb, cinfo, l2_of, l2_name)
        # --- 지난 날짜 (최근 7일 중 신규 공개가 있었던 날) — /{시도}/d{날짜}/
        for dd in days[1:]:
            day = now.replace(year=int(dd[:4]), month=int(dd[4:6]), day=int(dd[6:]))
            ddir = os.path.join(SITE, sdir, f"d{dd}")
            os.makedirs(ddir, exist_ok=True)
            arch = dict(base, date_label=day.strftime("%y.%m.%d"), date_full=dd, home_href="../../index.html", root="../../", apt_base=f"../../{sdir}/",
                        archive=True, page_url=None)
            s1, r1, _, _ = D.build_trades(subset_asof(sdb, set(sd["codes"]), dd), day, cinfo)
            favc += [c for c in s1["cards"] if c.get("h")]
            ind_d = D.build_indicator([t for t in sdb["sale"]["trades"] if (t.get("seen") or "") <= dd], day, *ind_args)
            cd = dict(arch, sale=s1, rent=r1, indicator=ind_d, has_ind=bool(ind_d["count"]), level=1,
                      region=sd["short"], region_full=sd["sido"], ind_rule=rule,
                      crumbs=[("전국", "../../index.html"), (sd["short"], None)],
                      dates=date_opts(days, dd, "index.html", True), seo_title=ctx["seo_title"], seo_desc=ctx["seo_desc"])
            with open(os.path.join(ddir, "index.html"), "w", encoding="utf-8") as f:
                f.write(tpl.render(cd))
            if len(sd["l2"]) > 1:
                for l in sd["l2"]:
                    sl = l2slug[l["key"]]
                    s2, r2, _, _ = D.build_trades(subset_asof(sdb, set(l["codes"]), dd), day, cinfo)
                    c2 = dict(arch, sale=s2, rent=r2, indicator=None, has_ind=False, level=2,
                              region=l["name"], region_full=f"{sd['sido']} {l['name']}",
                              crumbs=[("전국", "../../index.html"), (sd["short"], "index.html"), (l["name"], None)],
                              dates=date_opts(days, dd, f"{sl}.html", True),
                              seo_title=f"{sd['short']} {l['name']} 아파트 실거래가·신고가 | 옆집얼마", seo_desc="")
                    with open(os.path.join(ddir, f"{sl}.html"), "w", encoding="utf-8") as f:
                        f.write(tpl.render(c2))
        if key in APT_SIDOS:
            os.makedirs(os.path.join(SITE, "fav"), exist_ok=True)
            with open(os.path.join(SITE, "fav", f"{sdir}.json"), "w", encoding="utf-8") as f:
                json.dump(favc, f, ensure_ascii=False, separators=(",", ":"))
        home.append({"key": key, "short": sd["short"], "sido": sd["sido"], "href": f"{sdir}/index.html",
                     "ready": ready, "cnt": sale_ctx["cnt"], "high": sale_ctx["high_cnt"], "rent": rent_ctx["cnt"],
                     "avg84": avg84(sdb["sale"]["trades"], now), "l2_word": l2_word, "chips": chips})
        print(f"🧾 {sd['short']}: 신규 매매 {sale_ctx['cnt']} · 신고가 {sale_ctx['high_cnt']} · 페이지 {1 + len(chips)}개")

    # 홈 막대그래프: 최근 30일 날짜별 '신규 공개 매매' 건수 (홈 숫자와 같은 기준 = 그날 새로 공개된 매매+분양권)
    # 날마다 store/home_daily.json 에 쌓는다. 처음 한 번은 거래의 공개일(seen)로 아는 날을 채운다 (전국 수집 시작 11.14 부터).
    dpath = os.path.join(STORE, "home_daily.json")
    try:
        with open(dpath, encoding="utf-8") as f:
            hist_d = json.load(f)
    except (OSError, ValueError):
        hist_d = {}
    tot_cnt = sum(h["cnt"] for h in home)
    if not args.only:   # 일부 시도만 만든 시험 빌드는 기록하지 않음
        from collections import Counter
        seen_c = Counter(t.get("seen") for src in ("sale", "pre") for sd in sidos for t in dbs[src][sd["key"]]["trades"])
        for d, c in seen_c.items():
            if d and d >= "20261114" and d not in hist_d:
                hist_d[d] = c
        hist_d[now.strftime("%Y%m%d")] = tot_cnt
        hist_d = dict(sorted(hist_d.items())[-120:])
        with open(dpath, "w", encoding="utf-8") as f:
            json.dump(hist_d, f, separators=(",", ":"))
    daily = []
    for i in range(29, -1, -1):
        d = (now - timedelta(days=i)).strftime("%Y%m%d")
        daily.append([d, hist_d.get(d)])
    if args.only and daily[-1][1] is None:
        daily[-1][1] = tot_cnt
    hc = {"date_label": now.strftime("%y.%m.%d"), "sidos": home, "site_url": SITE_URL, "daily": daily,
          "tot": {k: sum(h[k] for h in home) for k in ("cnt", "high", "rent")},
          "max_cnt": max([h["cnt"] for h in home] + [1])}
    with open(os.path.join(SITE, "index.html"), "w", encoding="utf-8") as f:
        f.write(env.get_template("home.html").render(hc))
    with open(os.path.join(SITE, "pop.html"), "w", encoding="utf-8") as f:   # 인기단지 (많이 산 단지 · 실시간 검색)
        f.write(env.get_template("pop.html").render(today=now.strftime("%Y%m%d"),
                sidos=[["전남광주" if h["short"] == "광주전남" else h["short"], h["href"].split("/")[0]] for h in home if h["key"] in APT_SIDOS]))
    act_nat["s"].sort(key=lambda r: -r["r3"])
    act_nat["g"] = sorted(act_nat["g"], key=lambda r: -r["r3"])[:20]   # 전국 시군구 Top 20
    with open(os.path.join(SITE, "act.html"), "w", encoding="utf-8") as f:   # 거래활발도 (시도별 · 전국 시군구 · 지표단지 · 구군별)
        f.write(env.get_template("act.html").render(today=now.strftime("%Y%m%d"), nat=act_nat, sidos=act_sidos,
                date_label=now.strftime("%y.%m.%d")))
    import rate, budget   # 금리 (한국은행 ECOS, 하루 한 번)
    rate_d = rate.build(STORE)
    with open(os.path.join(SITE, "rate.html"), "w", encoding="utf-8") as f:
        f.write(env.get_template("rate.html").render(today=now.strftime("%Y%m%d"), rate=rate_d))
    mort = (rate_d.get("mort") or [[None, 4.5]])[-1]
    with open(os.path.join(SITE, "budget.html"), "w", encoding="utf-8") as f:   # 나의 예산 (예산 계산 + 맞춤 추천)
        f.write(env.get_template("budget.html").render(today=now.strftime("%Y%m%d"), rules=budget.RULES, sidos=bud_sidos,
                mort={"v": mort[1], "m": mort[0] or ""}))
    with open(os.path.join(SITE, "sub.html"), "w", encoding="utf-8") as f:   # 청약단지
        f.write(env.get_template("sub.html").render(today=now.strftime("%Y%m%d"), sidos=sub_sidos))
    with open(os.path.join(SITE, "hi.html"), "w", encoding="utf-8") as f:   # 최고가 (기간·지역·평형별)
        f.write(env.get_template("hi.html").render(today=now.strftime("%Y%m%d"),
                sidos=[["전남광주" if h["short"] == "광주전남" else h["short"], h["href"].split("/")[0]] for h in home if h["key"] in APT_SIDOS]))
    with open(os.path.join(SITE, "push.json"), "w", encoding="utf-8") as f:
        json.dump(push, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(SITE, "fav.html"), "w", encoding="utf-8") as f:   # 관심단지 (기기에 저장한 단지의 최근 7일 거래)
        f.write(env.get_template("fav.html").render(today=now.strftime("%Y%m%d")))
    with open(os.path.join(SITE, "search.json"), "w", encoding="utf-8") as f:   # 단지 검색 목록 [이름, 위치, 주소, 거래수]
        json.dump(sorted(search, key=lambda a: -a[3]), f, ensure_ascii=False, separators=(",", ":"))
    # 검색엔진용: 사이트맵 · robots.txt
    today_iso = now.strftime("%Y-%m-%d")
    with open(os.path.join(SITE, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for u in [f"{SITE_URL}/"] + urls:
            f.write(f"<url><loc>{u}</loc><lastmod>{today_iso}</lastmod><changefreq>daily</changefreq></url>\n")
        f.write("</urlset>\n")
    with open(os.path.join(SITE, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(f"User-agent: *\nAllow: /\nDisallow: /r/\n\nSitemap: {SITE_URL}/sitemap.xml\n")
    if D.MOLIT_API_KEY:
        for src in D.SOURCES:
            for sd in sidos:
                db = dbs[src][sd["key"]]
                for t in db["trades"]:
                    t.pop("l2", None)
                save_db(src, sd["key"], db)
    print(f"✅ site/ 생성 완료 ({len(home)}개 시도)")


if __name__ == "__main__":
    main()
