"""부산 아파트 실거래 대시보드 생성기.

동작 개요
---------
1. 국토부 실거래 3종(아파트 매매 · 분양권 전매 · 전월세)을 최근 13개월치 data/*.json 에 저장합니다.
2. 매일 최근 3개월을 다시 받아 DB 를 갱신합니다. 어제까지 DB 에 없던 거래 = "오늘 새로 공개된 실거래".
3. 매매(분양권 포함)는 같은 단지·같은 전용면적의 기존 최고가, 전세는 기존 최고 보증금을 넘으면 신고가.
4. 지표단지 세대수 대비 거래량(회전율)을 최근 1년 / 3개월로 계산합니다.
5. templates/report_template.html 로 index.html 을 만듭니다.

사용법
------
    python Dashboard.py              # 일일 갱신 (DB 가 비어 있으면 13개월 전체 수집)
    python Dashboard.py --rebuild    # 국토부 DB 를 처음부터 다시 수집
    python Dashboard.py --demo       # API 없이 예시 데이터로 demo.html 생성
"""

import argparse
import json
import os
import random
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import requests
from jinja2 import Environment, FileSystemLoader

# ==========================================
# 1. 설정
# ==========================================
MOLIT_API_KEY = os.environ.get("MOLIT_API_KEY", "")
API = "https://apis.data.go.kr/1613000"
SOURCES = {
    # 키: (API 주소, 저장 파일, 이름)
    "sale": (f"{API}/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev", "data/real_estate_db.json", "아파트 매매"),
    "pre": (f"{API}/RTMSDataSvcSilvTrade/getRTMSDataSvcSilvTrade", "data/presale_db.json", "분양권 전매"),
    "rent": (f"{API}/RTMSDataSvcAptRent/getRTMSDataSvcAptRent", "data/rent_db.json", "아파트 전월세"),
}
WINDOW_MONTHS = 13   # DB 에 보관할 개월 수 (1년 회전율 계산용)
REFRESH_MONTHS = 3   # 매일 다시 받아올 최근 개월 수
LIST_LEN = 15        # 타입별 리스트 최대 건수
RENT_PER_EOK = 40    # 월세 40만원 = 보증금 1억원으로 환산
KST = timezone(timedelta(hours=9))

BUSAN_LAWD_CD = {
    "중구": "26110", "서구": "26140", "동구": "26170", "영도구": "26200",
    "부산진구": "26230", "동래구": "26260", "남구": "26290", "북구": "26320",
    "해운대구": "26350", "사하구": "26380", "금정구": "26410", "강서구": "26440",
    "연제구": "26470", "수영구": "26500", "사상구": "26530", "기장군": "26710",
}

# 지표단지 설정
#  - name: 화면에 표시할 이름
#  - households: 세대수
#  - keywords(선택): 국토부 단지명과 다를 때 매칭할 이름들 (공백·괄호·특수문자는 무시하고 '포함' 여부로 비교)
INDICATOR_COMPLEXES = {
    "수영구": [
        {"name": "삼익비치", "households": 3060},
        {"name": "남천자이", "households": 913},
        {"name": "남천더샵프레스티지", "households": 975, "keywords": ["더샵남천프레스티지"]},
    ],
    "해운대구": [
        {"name": "해운대자이2차1단지", "households": 813},
        {"name": "더샵센텀파크1차", "households": 2752},
    ],
    "남구": [
        {"name": "대연힐스테이트푸르지오", "households": 2304},
        {"name": "더비치푸르지오써밋", "households": 1384},
    ],
    "동래구": [
        {"name": "동래래미안아이파크", "households": 3853},
        {"name": "사직롯데캐슬더클래식", "households": 1064},
    ],
    "연제구": [
        {"name": "레이카운티", "households": 4470},
        {"name": "연산롯데캐슬골드포레", "households": 1450},
    ],
    "부산진구": [
        {"name": "삼한골든뷰센트럴파크", "households": 1272},
    ],
    "금정구": [
        {"name": "래미안장전", "households": 1938},
    ],
    "강서구": [
        {"name": "명지더샵퍼스트월드3단지", "households": 1530, "keywords": ["더샵명지퍼스트월드3단지"]},
    ],
    "북구": [
        {"name": "화명롯데캐슬카이저", "households": 5239},
    ],
    "사상구": [
        {"name": "사상중흥S-클래스그랜드센트럴", "households": 1508, "keywords": ["사상중흥에스클래스그랜드센트럴"]},
    ],
    "사하구": [
        {"name": "힐스테이트사하역", "households": 1314},
    ],
    "동구": [
        {"name": "두산위브더제니스하버시티", "households": 2040},
    ],
    "서구": [
        {"name": "대신푸르지오2차", "households": 815},
    ],
    "영도구": [
        {"name": "봉래에일린의뜰", "households": 1216, "keywords": ["영도센트럴에일린의뜰"]},
    ],
    "기장군": [
        {"name": "일광자이푸르지오", "households": 1547},
    ],
}




# ==========================================
# 2. 공통 유틸
# ==========================================
def normalize(s):
    return re.sub(r"[^0-9A-Za-z가-힣]", "", s or "").lower()


def area_type(a):
    """전용면적 → 타입 (59: 55~65㎡ 미만, 84: 78~88㎡, 나머지 기타)"""
    if 55 <= a < 65:
        return "59타입"
    if 78 <= a <= 88:
        return "84타입"
    return "기타"


TYPES = ["84타입", "59타입", "기타"]


def fmt_price(p):
    """만원 → '18억6,000만' / '22억' / '9,500만'"""
    p = int(p)
    eok, man = divmod(abs(p), 10000)
    sign = "-" if p < 0 else ""
    if eok and man:
        return f"{sign}{eok}억{man:,}만"
    if eok:
        return f"{sign}{eok}억"
    return f"{sign}{man:,}만"


def fmt_short(p):
    """만원 → '18억6,000' / '22억' / '9,500만' (리스트용 짧은 표기)"""
    s = fmt_price(p)
    return s[:-1] if "억" in s and s.endswith("만") else s


def ymd_label(s):
    return f"{s[2:4]}.{s[4:6]}.{s[6:8]}" if s else ""


def month_list(today, n):
    """오늘이 속한 달부터 과거로 n개월 (YYYYMM, 최신순)"""
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def months_ago(today, n):
    y, m = today.year, today.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    for d in range(today.day, 0, -1):   # 말일 보정
        try:
            return today.replace(year=y, month=m, day=d)
        except ValueError:
            continue


def high_key(t):
    """신고가 비교 단위: 같은 구 + 같은 단지명 + 같은 전용면적(정수 반올림). 매매·분양권 공통."""
    return f"{t['d']}|{normalize(t['n'])}|{round(t['a'])}"


def pyeong(a):
    """전용면적 → 평형(공급면적 기준 추정). 실거래 자료에는 공급면적이 없어 전용률 75%로 환산 (84㎡≈34평, 59㎡≈24평)."""
    return round(a / 0.75 / 3.3058) if a else None


def floor_label(f):
    f = str(f or "").strip()
    return f"{f}층" if f.lstrip("-").isdigit() else (f or "-")


# ==========================================
# 3. 국토교통부 실거래가 API 수집
# ==========================================
class FetchError(Exception):
    pass


def _text(item, *tags):
    for tag in tags:
        v = item.findtext(tag)
        if v is not None and v.strip():
            return v.strip()
    return ""


def _num(s):
    s = (s or "").replace(",", "").strip()
    return int(s) if s.isdigit() else None


def parse_item(src, item, district, deal_ym):
    if _text(item, "cdealType", "해제여부") == "O" or _text(item, "cdealDay", "해제사유발생일"):
        return None   # 계약 해제 건 제외
    name = _text(item, "aptNm", "아파트", "단지")
    if not name:
        return None
    try:
        area = float(_text(item, "excluUseAr", "전용면적") or 0)
    except ValueError:
        area = 0.0
    y = _text(item, "dealYear", "년") or deal_ym[:4]
    m = _text(item, "dealMonth", "월") or deal_ym[4:]
    dd = _text(item, "dealDay", "일") or "1"
    t = {"d": district, "u": _text(item, "umdNm", "법정동"), "n": name, "s": _text(item, "aptSeq"),
         "a": area, "f": _text(item, "floor", "층"), "dt": f"{int(y):04d}{int(m):02d}{int(dd):02d}",
         "dong": _text(item, "aptDong")}
    if src == "rent":
        dep = _num(_text(item, "deposit", "보증금액"))
        mon = _num(_text(item, "monthlyRent", "월세금액")) or 0
        if dep is None:
            return None
        t.update(p=dep, m=mon, ct=_text(item, "contractType", "계약구분"))
    else:
        p = _num(_text(item, "dealAmount", "거래금액"))
        if not p:
            return None
        t["p"] = p
    return t


def fetch_month(src, district, lawd_cd, deal_ym):
    """한 구/군의 한 달치 실거래. 실패 시 FetchError (기존 DB 데이터는 유지됨)."""
    url = SOURCES[src][0]
    trades, page = [], 1
    while True:
        params = {"serviceKey": requests.utils.unquote(MOLIT_API_KEY), "LAWD_CD": lawd_cd,
                  "DEAL_YMD": deal_ym, "pageNo": str(page), "numOfRows": "1000"}
        res = None
        for attempt in range(3):
            try:
                res = requests.get(url, params=params, timeout=30)
                if res.status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(2 ** attempt)
        if res is None or res.status_code != 200:
            body = res.text[:150] if res is not None else ""
            raise FetchError(f"{SOURCES[src][2]} HTTP {getattr(res, 'status_code', '-')} ({district} {deal_ym}) {body}")
        try:
            root = ET.fromstring(res.content)
        except ET.ParseError:
            raise FetchError(f"{SOURCES[src][2]} 응답 오류 ({district} {deal_ym}): {res.text[:150]}")
        code = root.findtext(".//resultCode", "")
        if code not in ("00", "000"):
            msg = root.findtext(".//resultMsg", "") or root.findtext(".//returnAuthMsg", "")
            raise FetchError(f"{SOURCES[src][2]} API 오류 ({district} {deal_ym}): {code} {msg}")

        items = root.findall(".//item")
        for item in items:
            t = parse_item(src, item, district, deal_ym)
            if t:
                trades.append(t)
        total = int(root.findtext(".//totalCount", "0") or 0)
        if not items or page * 1000 >= total:
            break
        page += 1

    seen = Counter()   # 거래 고유 ID (동일 조건 거래가 여러 건이면 #순번)
    for t in trades:
        rent_part = f"|{t['m']}" if src == "rent" else ""   # 매매 ID 형식은 예전과 동일하게 유지
        base = f"{t['d']}|{t['s'] or t['n']}|{t['a']}|{t['f']}|{t['dt']}|{t['p']}{rent_part}|{t['dong']}"
        seen[base] += 1
        t["id"] = f"{base}#{seen[base]}"
    return trades


# ==========================================
# 4. DB 로드 / 갱신 / 저장
# ==========================================
def load_db(src):
    path = SOURCES[src][1]
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                db = json.load(f)
            if db.get("version") == 2:
                return db
        except Exception:
            pass
    return {"version": 2, "trades": [], "fetched": []}


def save_db(src, db):
    path = SOURCES[src][1]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, separators=(",", ":"))


def update_db(src, db, today, rebuild=False):
    """API 로 DB 갱신. 반환: 실패 메시지 목록"""
    today_s = today.strftime("%Y%m%d")
    months = month_list(today, WINDOW_MONTHS)
    bootstrap = rebuild or not db["trades"]
    fetched = set() if rebuild else set(db.get("fetched", []))
    groups = defaultdict(list)
    if not rebuild:
        for t in db["trades"]:
            groups[(t["d"], t["dt"][:6])].append(t)
    old_ids = {t["id"]: t for g in groups.values() for t in g}

    errors, ok = [], 0
    for district, cd in BUSAN_LAWD_CD.items():
        for i, ym in enumerate(months):
            if not (bootstrap or i < REFRESH_MONTHS or f"{district}|{ym}" not in fetched):
                continue
            try:
                fresh = fetch_month(src, district, cd, ym)
            except FetchError as e:
                errors.append(str(e))
                print("⚠️", e)
                if len(errors) >= 5 and not ok:
                    return errors   # 키 미승인 등으로 처음부터 계속 실패하면 중단 (기존 DB 유지)
                continue
            for t in fresh:
                prev = old_ids.get(t["id"])
                t["seen"] = prev["seen"] if prev else ("" if bootstrap else today_s)
            ok += 1
            groups[(district, ym)] = fresh
            fetched.add(f"{district}|{ym}")

    oldest = months[-1]
    db["trades"] = [t for (d, ym), g in groups.items() if ym >= oldest for t in g]
    db["fetched"] = sorted(x for x in fetched if x.split("|")[1] >= oldest)
    db["updated_at"] = today.strftime("%Y-%m-%d %H:%M")
    return errors


# ==========================================
# 5. 리포트 데이터 계산
# ==========================================
def todays(trades, today):
    """오늘 새로 공개된 거래 = 어제까지 수집한 목록에 없다가 오늘 처음 들어온 거래."""
    today_s = today.strftime("%Y%m%d")
    return [t for t in trades if t.get("seen") == today_s]


def mark_highs(new, history, prior, value=lambda t: t["p"], eligible=lambda t: True):
    """new 각 거래에 'up'(신고가 여부)을 붙이고, 갱신된 최고가 맵을 돌려줌."""
    new_ids = {id(t) for t in new}
    base = dict(prior)
    for t in history:
        if id(t) in new_ids or not eligible(t):
            continue
        k = high_key(t)
        base[k] = max(base.get(k, 0), value(t))
    baseline = dict(base)   # 오늘 거래를 반영하기 전 기준 (같은 날 다시 실행해도 결과가 같도록 이 값을 저장)
    for t in sorted(new, key=lambda x: (x["dt"], value(x))):
        t["up"] = False
        if not eligible(t):
            continue
        k, v = high_key(t), value(t)
        if base.get(k) and v > base[k]:
            t["up"] = True
        base[k] = max(base.get(k, 0), v)
    return baseline


def build_trades(dbs, today):
    sale = [dict(t, src="sale") for t in dbs["sale"]["trades"]]
    pre = [dict(t, src="pre") for t in dbs["pre"]["trades"]]
    rent = [dict(t, src="rent") for t in dbs["rent"]["trades"]]

    new_sale = todays(sale, today)
    new_pre = todays(pre, today)
    new_rent = todays(rent, today)

    # 매매 + 분양권 (신고가도 함께 비교)
    new_s = new_sale + new_pre
    highs_s = mark_highs(new_s, sale + pre, dbs["sale"].get("highs3", {}))
    is_jeonse = lambda t: not t.get("m")
    highs_r = mark_highs(new_rent, rent, dbs["rent"].get("highs3", {}), eligible=is_jeonse)

    def srow(t):
        return {"name": t["n"], "py": pyeong(t["a"]), "floor": floor_label(t["f"]), "price": fmt_short(t["p"]), "p": t["p"],
                "type": area_type(t["a"]), "pre": t["src"] == "pre", "up": t["up"]}

    def rrow(t):
        mon = t.get("m") or 0
        return {"name": t["n"], "py": pyeong(t["a"]), "floor": floor_label(t["f"]), "type": area_type(t["a"]), "up": t["up"],
                "monthly": bool(mon), "conv": t["p"] + mon * 10000 // RENT_PER_EOK,
                "price": f"{fmt_short(t['p']) if t['p'] else '0'}/{mon:,}" if mon else fmt_short(t["p"])}

    srows = sorted((srow(t) for t in new_s), key=lambda r: -r["p"])
    rrows = sorted((rrow(t) for t in new_rent), key=lambda r: -r["conv"])

    def by_type(rows):
        return {k: [r for r in rows if r["type"] == k][:LIST_LEN] for k in TYPES}

    title = f"{today.strftime('%y.%m.%d')} 신규 실거래"

    type_cnt = Counter(r["type"] for r in srows)
    rent_type_cnt = Counter(r["type"] for r in rrows)
    sale_ctx = {
        "title": title, "cnt": len(srows),
        "pre_cnt": sum(1 for r in srows if r["pre"]), "high_cnt": sum(1 for r in srows if r["up"]),
        "type_cnt": type_cnt, "lists": by_type(srows), "top15": srows[:15],
    }
    rent_ctx = {
        "title": title, "cnt": len(rrows),
        "jeonse": sum(1 for r in rrows if not r["monthly"]), "wolse": sum(1 for r in rrows if r["monthly"]),
        "high_cnt": sum(1 for r in rrows if r["up"]), "type_cnt": rent_type_cnt,
        "lists": by_type(rrows), "top5": rrows[:5],
        "jeonse_top5": [r for r in rrows if not r["monthly"]][:5],
    }
    return sale_ctx, rent_ctx, highs_s, highs_r


def match_complex(name_keys, district, names):
    return [n for n in names if any(k in normalize(n) for k in name_keys)]


def build_indicator(sale_trades, today, gu_hh=None):
    today_s = today.strftime("%Y%m%d")
    d_1y = (today - timedelta(days=365)).strftime("%Y%m%d")
    d_3m = months_ago(today, 3).strftime("%Y%m%d")
    by_district = defaultdict(list)
    for t in sale_trades:
        by_district[t["d"]].append(t)

    groups, items = [], []
    for district, apts in INDICATOR_COMPLEXES.items():
        gi = []
        for apt in apts:
            kws = [normalize(k) for k in apt.get("keywords", [apt["name"]])]
            matched = [t for t in by_district.get(district, []) if any(k in normalize(t["n"]) for k in kws)]
            c1 = sum(1 for t in matched if d_1y < t["dt"] <= today_s)
            c3 = sum(1 for t in matched if d_3m < t["dt"] <= today_s)
            hh = apt["households"]
            it = {"name": apt["name"], "households": hh, "district": district,
                  "c1": c1, "r1": c1 / hh * 100, "c3": c3, "r3": c3 / hh * 100}
            change = (c3 * 4 / c1 - 1) * 100 if c1 else 0
            it["change"] = round(change)
            it["trend"] = ("strong" if change >= 10 else "up" if change >= 5 else
                           "weak" if change <= -10 else "down" if change <= -5 else "")
            gi.append(it)
            items.append(it)
        groups.append({"district": district, "items": gi})

    max_r1 = max([i["r1"] for i in items] + [0.01])
    max_r3 = max([i["r3"] for i in items] + [0.01])
    for i in items:
        i["w1"] = round(i["r1"] / max_r1 * 100, 1)
        i["w3"] = round(i["r3"] / max_r3 * 100, 1)
    hh = sum(i["households"] for i in items)
    c1 = sum(i["c1"] for i in items)
    c3 = sum(i["c3"] for i in items)
    by_r3 = sorted(items, key=lambda i: -i["r3"])
    # 구별 거래량 (해당 구 전체 아파트 매매, 1년 / 3개월)
    gus = []
    for district in BUSAN_LAWD_CD:
        ts = by_district.get(district, [])
        g1 = sum(1 for t in ts if d_1y < t["dt"] <= today_s)
        g3 = sum(1 for t in ts if d_3m < t["dt"] <= today_s)
        ghh = (gu_hh or {}).get(district)
        gus.append({"name": district, "c1": g1, "c3": g3, "hh": ghh,
                    "r1": g1 / ghh * 100 if ghh else None, "r3": g3 / ghh * 100 if ghh else None})
    gu_rate = bool(gus) and all(g["hh"] for g in gus)   # 모든 구 세대수가 있을 때만 회전율로 표시
    k1, k3 = ("r1", "r3") if gu_rate else ("c1", "c3")
    gus.sort(key=lambda g: -g[k3])
    m1 = max([g[k1] for g in gus] + [0.0001])
    m3 = max([g[k3] for g in gus] + [0.0001])
    for g in gus:
        g["w1"], g["w3"] = round(g[k1] / m1 * 100, 1), round(g[k3] / m3 * 100, 1)
    return {
        "groups": groups, "count": len(items), "households": hh,
        "c1": c1, "r1": c1 / hh * 100 if hh else 0, "c3": c3, "r3": c3 / hh * 100 if hh else 0,
        "top5_1y": sorted(items, key=lambda i: -i["r1"])[:5], "top5_3m": by_r3[:5], "by_r3": by_r3, "gus": gus, "gu_rate": gu_rate,
        "period_1y": f"{ymd_label(d_1y)}~", "period_3m": f"{ymd_label(d_3m)}~",
    }


# ==========================================
# 6. HTML 생성
# ==========================================
def render(context, out_path):
    env = Environment(loader=FileSystemLoader("templates"), autoescape=True)
    html = env.get_template("report_template.html").render(context)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ {out_path} 생성 완료")


def build_context(dbs, today, gu_hh=None):
    sale_ctx, rent_ctx, highs_s, highs_r = build_trades(dbs, today)
    indicator = build_indicator(dbs["sale"]["trades"], today, gu_hh)
    return {
        "date_label": today.strftime("%y.%m.%d"), "date_full": today.strftime("%Y%m%d"),
        "sale": sale_ctx, "rent": rent_ctx, "indicator": indicator, "notices": [],
    }, highs_s, highs_r


# ==========================================
# 7. 예시 데이터 (--demo)
# ==========================================
def demo_dbs(today):
    rnd = random.Random(7)
    today_s = today.strftime("%Y%m%d")
    names = [(d, a["name"], a["households"]) for d, apts in INDICATOR_COMPLEXES.items() for a in apts]
    extra = [("해운대구", "엘시티더샵"), ("해운대구", "마린시티자이"), ("해운대구", "해운대아이파크"),
             ("남구", "더블유"), ("부산진구", "래미안어반파크"), ("동래구", "명륜자이")]
    dbs = {k: {"version": 2, "trades": [], "fetched": []} for k in SOURCES}

    def add(src, d, n, a, f, p, dt, seen="", m=0):
        t = {"id": f"{src}{len(dbs[src]['trades'])}", "d": d, "u": "", "n": n, "s": "", "a": a, "f": str(f),
             "p": p, "dt": dt, "seen": seen, "dong": ""}
        if src == "rent":
            t["m"] = m
        dbs[src]["trades"].append(t)

    areas = [84.95, 84.97, 59.98, 59.9, 101.9, 124.4, 144.6]
    for d, n, hh in names:
        for _ in range(int(hh * rnd.uniform(0.03, 0.07))):
            days = int(rnd.random() ** rnd.uniform(0.7, 1.3) * 360) + 2
            add("sale", d, n, rnd.choice(areas[:4]), rnd.randint(2, 35), rnd.randint(30000, 110000),
                (today - timedelta(days=days)).strftime("%Y%m%d"))
    pool = [(d, n) for d, n, _ in names] + extra
    for i in range(104):
        d, n = rnd.choice(pool)
        a = rnd.choice(areas)
        base = int((a * 1100) * rnd.uniform(0.6, 2.6))
        add("sale", d, n, a, rnd.randint(2, 60), base, (today - timedelta(days=200)).strftime("%Y%m%d"))
        add("sale", d, n, a, rnd.randint(2, 60), int(base * rnd.uniform(0.85, 1.08)),
            (today - timedelta(days=rnd.randint(3, 30))).strftime("%Y%m%d"), seen=today_s)
    for i in range(6):
        add("pre", "강서구", "에코델타시티푸르지오", rnd.choice(areas[:4]), rnd.randint(3, 30),
            rnd.randint(52000, 152000), (today - timedelta(days=rnd.randint(3, 20))).strftime("%Y%m%d"), seen=today_s)
    for i in range(239):
        d, n = rnd.choice(pool)
        a = rnd.choice(areas)
        if i % 3 == 0:
            dep, mon = rnd.choice([1000, 3000, 5000, 10000, 20000, 30000]), rnd.randint(40, 650)
        else:
            dep, mon = int(a * 650 * rnd.uniform(0.6, 1.8)), 0
        if not mon:
            add("rent", d, n, a, rnd.randint(2, 40), int(dep * 0.95), (today - timedelta(days=200)).strftime("%Y%m%d"))
        add("rent", d, n, a, rnd.randint(2, 40), dep, (today - timedelta(days=rnd.randint(3, 30))).strftime("%Y%m%d"),
            seen=today_s, m=mon)
    return dbs


# ==========================================
# 8. 메인
# ==========================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true", help="국토부 DB 전체 재수집")
    ap.add_argument("--demo", action="store_true", help="예시 데이터로 렌더링")
    ap.add_argument("--out", default=None, help="출력 HTML 경로")
    args = ap.parse_args()
    now = datetime.now(KST)

    if args.demo:
        ctx, _, _ = build_context(demo_dbs(now), now)
        ctx["notices"].append("예시 데이터로 생성된 미리보기입니다.")
        render(ctx, args.out or "demo.html")
        return

    dbs = {k: load_db(k) for k in SOURCES}
    errors = {}
    if MOLIT_API_KEY:
        for src in SOURCES:
            if args.rebuild:
                dbs[src] = {"version": 2, "trades": [], "fetched": []}
            print(f"🔍 {SOURCES[src][2]} 수집...")
            errors[src] = update_db(src, dbs[src], now, rebuild=args.rebuild)
            print(f"✅ {SOURCES[src][2]} DB {len(dbs[src]['trades']):,}건 (실패 {len(errors[src])}건)")
    else:
        print("⚠️ MOLIT_API_KEY 가 없어 기존 DB 로만 리포트를 만듭니다.")

    import households
    gu_hh = households.ensure(BUSAN_LAWD_CD, now)
    ctx, highs_s, highs_r = build_context(dbs, now, gu_hh)
    for src, errs in errors.items():
        if errs and not dbs[src]["trades"]:
            ctx["notices"].append(f"{SOURCES[src][2]} 실거래를 받지 못했습니다: {errs[0][:80]}")
        elif errs:
            ctx["notices"].append(f"{SOURCES[src][2]} 일부 수집 실패 {len(errs)}건 — 이전 데이터로 대체")
    if MOLIT_API_KEY:
        dbs["sale"]["highs3"] = highs_s
        dbs["rent"]["highs3"] = highs_r
        for src in SOURCES:
            save_db(src, dbs[src])
    render(ctx, args.out or "index.html")


if __name__ == "__main__":
    main()
