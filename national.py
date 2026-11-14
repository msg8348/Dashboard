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
import kapt
import regions

STORE = os.environ.get("STORE_DIR", "store")
SITE = "site"
SITE_URL = "https://nextdoorprice.com"
regions.PATH = os.path.join(STORE, "regions.json")
IND_PATH = os.path.join(STORE, "indicators.json")
BUSAN = "26"
WORKERS = int(os.environ.get("FETCH_WORKERS", "8"))   # 동시 요청 수


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
    env = Environment(loader=FileSystemLoader("templates"), autoescape=True)
    tpl = env.get_template("report_template.html")
    shutil.rmtree(SITE, ignore_errors=True)
    if os.path.isdir("static"):   # 아이콘·매니페스트
        shutil.copytree("static", SITE)
    months = D.month_list(now, D.WINDOW_MONTHS)
    urls = []
    home = []
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
        base = {"date_label": now.strftime("%y.%m.%d"), "date_full": now.strftime("%Y%m%d"), "notices": [],
                "l2_word": l2_word, "home_href": "../index.html", "root": "../", "site_url": SITE_URL}
        if not ready:
            base["notices"].append("이 지역은 실거래 데이터를 수집하고 있습니다. 며칠 안에 채워집니다.")
        # --- 레벨1
        sale_ctx, rent_ctx, highs_s, highs_r = D.build_trades(subset(sdb, set(sd["codes"])), now)
        if not fallback:   # 날짜별 기준값도 보관 (최근 3일) — 신규 공개가 없는 날 전날 기준으로 다시 보여줄 때 사용
            for src, h in (("sale", highs_s), ("rent", highs_r)):
                by = sdb[src].setdefault("highs3_by", {})
                by[now.strftime("%Y%m%d")] = h
                for d in sorted(by)[:-3]:
                    by.pop(d)
            sdb["sale"]["highs3"], sdb["rent"]["highs3"] = highs_s, highs_r
        kapt_l2 = kapt_rows_by_l2(sd)
        l2_hh = {l2_name[k]: sum(r["households"] for r in rows) for k, rows in kapt_l2.items()}
        if key == BUSAN:
            ind = D.build_indicator(sdb["sale"]["trades"], now, l2_hh, D.INDICATOR_COMPLEXES, "d",
                                    [l["name"] for l in sd["l2"]])
            rule = "부산 지표단지 21곳 (직접 지정)"
        else:
            complete = {l["key"] for l in sd["l2"] if all(f"{c}|{ym}" in fetched for c in l["codes"] for ym in months)}
            picks = pick_indicators(sd, sdb["sale"]["trades"], now, kapt_l2, l2_of, complete)
            cx = {l2_name[k]: [{"name": p["name"], "households": p["households"],
                                "keywords": p.get("names") or [p["name"]], "exact": True, "avg84": D.fmt_short(p["avg84"]) if p["avg84"] else "",
                                "rule": p.get("rule", "")}] for k, p in picks.items()}
            ind = D.build_indicator(sdb["sale"]["trades"], now, l2_hh, cx, "l2", [l["name"] for l in sd["l2"]])
            rule = f"{l2_word}별 최근 1년 84타입 평균거래가 상위 5위 안에서 거래량 최다 단지 · 84타입 거래가 없으면 거래 최다 단지 · {quarter(now)} 고정"
        ctx = dict(base, sale=sale_ctx, rent=rent_ctx, indicator=ind, has_ind=bool(ind["count"]), level=1,
                   region=sd["short"], region_full=sd["sido"], ind_rule=rule,
                   crumbs=[("전국", "../index.html"), (sd["short"], None)], page_url=f"{SITE_URL}/{sdir}/",
                   seo_title=f"{sd['short']} 아파트 실거래가·신고가 | 옆집얼마",
                   seo_desc=f"{sd['short']} 아파트 실거래가와 신고가를 매일 알려드립니다. {sd['sido']} {l2_word}별 신규 매매·전월세 최고가와 지표단지 거래량 — 옆집얼마")
        urls.append(f"{SITE_URL}/{sdir}/")
        redirect(f"r/{key}/index.html", f"{sdir}/index.html")   # 예전 주소 → 새 주소
        with open(os.path.join(SITE, sdir, "index.html"), "w", encoding="utf-8") as f:
            f.write(tpl.render(ctx))
        # --- 레벨2
        chips = []
        if len(sd["l2"]) > 1:
            for l in sd["l2"]:
                s2, r2, _, _ = D.build_trades(subset(sdb, set(l["codes"])), now)
                c2 = dict(base, sale=s2, rent=r2, indicator=None, has_ind=False, level=2,
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
        home.append({"key": key, "short": sd["short"], "sido": sd["sido"], "href": f"{sdir}/index.html",
                     "ready": ready, "cnt": sale_ctx["cnt"], "high": sale_ctx["high_cnt"], "rent": rent_ctx["cnt"],
                     "avg84": avg84(sdb["sale"]["trades"], now), "l2_word": l2_word, "chips": chips})
        print(f"🧾 {sd['short']}: 신규 매매 {sale_ctx['cnt']} · 신고가 {sale_ctx['high_cnt']} · 페이지 {1 + len(chips)}개")

    hc = {"date_label": now.strftime("%y.%m.%d"), "sidos": home, "site_url": SITE_URL,
          "tot": {k: sum(h[k] for h in home) for k in ("cnt", "high", "rent")},
          "max_cnt": max([h["cnt"] for h in home] + [1])}
    with open(os.path.join(SITE, "index.html"), "w", encoding="utf-8") as f:
        f.write(env.get_template("home.html").render(hc))
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
