"""부산 아파트 매매 실거래 대시보드 생성기.

동작 개요
---------
1. data/real_estate_db.json 에 최근 13개월치 실거래를 저장해 둡니다.
2. 매일 실행 시 최근 3개월(신고 기한 30일 + 해제 반영)을 다시 받아 DB 를 갱신합니다.
   - 어제까지 DB 에 없던 거래 = "오늘 신규 공개된 실거래"
3. 신규 실거래 중 같은 단지·같은 평형의 기존 최고가를 넘으면 "신고가" 로 집계합니다.
4. 지표단지별 세대수 대비 거래량(회전율)을 최근 1년 / 3개월로 계산합니다.
5. templates/report_template.html 로 index.html 을 만듭니다. (이미지 저장 버튼 포함)

사용법
------
    python Dashboard.py              # 일일 갱신 (DB 가 비어 있으면 13개월 전체 수집)
    python Dashboard.py --rebuild    # DB 를 처음부터 다시 수집
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
# 국토교통부 아파트 매매 실거래가 상세 자료 (2024년 개편된 신규 Endpoint)
API_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
DB_PATH = "data/real_estate_db.json"
WINDOW_MONTHS = 13   # DB 에 보관할 개월 수 (1년 회전율 계산용)
REFRESH_MONTHS = 3   # 매일 다시 받아올 최근 개월 수
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


def fmt_price(p):
    """만원 단위 정수 -> '18억6,000만' / '22억' / '9,500만'"""
    p = int(p)
    eok, man = divmod(abs(p), 10000)
    sign = "-" if p < 0 else ""
    if eok and man:
        return f"{sign}{eok}억{man:,}만"
    if eok:
        return f"{sign}{eok}억"
    return f"{sign}{man:,}만"


def fmt_diff(d):
    if d > 0:
        return "+" + fmt_price(d)
    if d < 0:
        return fmt_price(d)
    return "동일"


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
    # 말일 보정 (예: 5/31 의 3개월 전 = 2/28)
    for d in range(today.day, 0, -1):
        try:
            return today.replace(year=y, month=m, day=d)
        except ValueError:
            continue


def price_key(t):
    """신고가 비교 단위: 같은 구 + 같은 단지 + 같은 전용면적(정수 반올림)"""
    return f"{t['d']}|{t.get('s') or t['n']}|{round(t['a'])}"


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


def fetch_month(district, lawd_cd, deal_ym):
    """한 구/군의 한 달치 매매 실거래. 실패 시 FetchError (기존 DB 데이터는 유지됨)."""
    trades, page = [], 1
    while True:
        params = {
            "serviceKey": requests.utils.unquote(MOLIT_API_KEY),
            "LAWD_CD": lawd_cd,
            "DEAL_YMD": deal_ym,
            "pageNo": str(page),
            "numOfRows": "1000",
        }
        res = None
        for attempt in range(3):
            try:
                res = requests.get(API_URL, params=params, timeout=20)
                if res.status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(2 ** attempt)
        if res is None or res.status_code != 200:
            raise FetchError(f"HTTP 오류 ({district} {deal_ym})")

        try:
            root = ET.fromstring(res.content)
        except ET.ParseError:
            raise FetchError(f"XML 파싱 실패 ({district} {deal_ym}): {res.text[:200]}")

        code = root.findtext(".//resultCode", "")
        if code not in ("00", "000"):
            msg = root.findtext(".//resultMsg", "") or root.findtext(".//returnAuthMsg", "")
            raise FetchError(f"API 오류 ({district} {deal_ym}): {code} {msg}")

        items = root.findall(".//item")
        for item in items:
            # 계약 해제 건 제외
            if _text(item, "cdealType", "해제여부") == "O" or _text(item, "cdealDay", "해제사유발생일"):
                continue
            name = _text(item, "aptNm", "아파트", "단지")
            price = _text(item, "dealAmount", "거래금액").replace(",", "")
            if not name or not price.isdigit():
                continue
            y = _text(item, "dealYear", "년") or deal_ym[:4]
            m = _text(item, "dealMonth", "월") or deal_ym[4:]
            dd = _text(item, "dealDay", "일") or "1"
            try:
                area = float(_text(item, "excluUseAr", "전용면적") or 0)
            except ValueError:
                area = 0.0
            trades.append({
                "d": district,
                "u": _text(item, "umdNm", "법정동"),
                "n": name,
                "s": _text(item, "aptSeq"),
                "a": area,
                "f": _text(item, "floor", "층"),
                "p": int(price),
                "dt": f"{int(y):04d}{int(m):02d}{int(dd):02d}",
                "dong": _text(item, "aptDong"),
            })

        total = int(root.findtext(".//totalCount", "0") or 0)
        if not items or page * 1000 >= total:
            break
        page += 1

    # 거래 고유 ID (동일 조건 거래가 여러 건이면 #순번으로 구분)
    seen = Counter()
    for t in trades:
        base = f"{t['d']}|{t['s'] or t['n']}|{t['a']}|{t['f']}|{t['dt']}|{t['p']}|{t['dong']}"
        seen[base] += 1
        t["id"] = f"{base}#{seen[base]}"
    return trades


# ==========================================
# 4. DB 로드 / 갱신 / 저장
# ==========================================
def load_db():
    if os.path.exists(DB_PATH):
        try:
            with open(DB_PATH, "r", encoding="utf-8") as f:
                db = json.load(f)
            # 예전 형식(init_db.yml 로 만든 DB)은 호환되지 않으므로 새로 수집
            if db.get("version") == 2:
                return db
        except Exception:
            pass
    return {"version": 2, "trades": [], "fetched": [], "high_prices": {}}


def save_db(db):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, separators=(",", ":"))


def update_db(db, today, rebuild=False):
    """API 로 DB 갱신. 반환: (bootstrap 여부, 실패 목록)"""
    today_s = today.strftime("%Y%m%d")
    months = month_list(today, WINDOW_MONTHS)
    bootstrap = rebuild or not db["trades"]
    fetched = set() if rebuild else set(db.get("fetched", []))

    groups = defaultdict(list)
    if not rebuild:
        for t in db["trades"]:
            groups[(t["d"], t["dt"][:6])].append(t)
    old_ids = {t["id"]: t for g in groups.values() for t in g}

    errors = []
    for district, cd in BUSAN_LAWD_CD.items():
        for i, ym in enumerate(months):
            if not (bootstrap or i < REFRESH_MONTHS or f"{district}|{ym}" not in fetched):
                continue
            try:
                fresh = fetch_month(district, cd, ym)
            except FetchError as e:
                errors.append(str(e))
                print("⚠️", e)
                continue
            for t in fresh:
                prev = old_ids.get(t["id"])
                t["seen"] = prev["seen"] if prev else ("" if bootstrap else today_s)
            groups[(district, ym)] = fresh
            fetched.add(f"{district}|{ym}")

    oldest = months[-1]
    db["trades"] = [t for (d, ym), g in groups.items() if ym >= oldest for t in g]
    db["fetched"] = sorted(x for x in fetched if x.split("|")[1] >= oldest)
    db["updated_at"] = today.strftime("%Y-%m-%d %H:%M")
    return bootstrap, errors


# ==========================================
# 5. 리포트 데이터 계산
# ==========================================
def build_report(trades, prior_high, today, bootstrap):
    today_s = today.strftime("%Y%m%d")
    yesterday_s = (today - timedelta(days=1)).strftime("%Y%m%d")

    # 5-1. "오늘" 집계 대상
    if bootstrap:
        # 최초 수집일에는 '신규 공개분'을 알 수 없으므로 전일 계약분으로 대체
        today_set = [t for t in trades if t["dt"] == yesterday_s]
        today_title = f"{yesterday_s[2:4]}.{yesterday_s[4:6]}.{yesterday_s[6:]} 계약 실거래"
        today_note = "최초 수집일 · 전일 계약분 기준"
    else:
        today_set = [t for t in trades if t.get("seen") == today_s]
        today_title = f"{today.strftime('%y.%m.%d')} 신규 실거래"
        today_note = "국토부 실거래 신규 공개분 기준"
    today_ids = {t["id"] for t in today_set}

    # 5-2. 기존 최고가 (오늘 집계 대상을 제외한 모든 과거 거래)
    baseline = dict(prior_high)
    for t in trades:
        if t["id"] in today_ids or (bootstrap and t["dt"] >= yesterday_s):
            continue
        k = price_key(t)
        if t["p"] > baseline.get(k, 0):
            baseline[k] = t["p"]

    rows, highs = [], []
    running = dict(baseline)
    for t in sorted(today_set, key=lambda x: (x["dt"], x["p"])):
        k = price_key(t)
        prev = running.get(k, 0)
        row = {
            "apt_name": t["n"],
            "meta": f"{t['d']} {t['u']} · {t['a']:g}㎡ · {t['f']}층 · {int(t['dt'][4:6])}.{int(t['dt'][6:])}",
            "price": fmt_price(t["p"]),
            "p": t["p"],
            "diff": fmt_diff(t["p"] - prev) if prev else "첫 거래",
            "up": prev and t["p"] > prev,
        }
        rows.append(row)
        if prev and t["p"] > prev:
            highs.append(row)
        if t["p"] > prev:
            running[k] = t["p"]

    top10 = sorted(rows, key=lambda r: r["p"], reverse=True)[:10]
    high5 = sorted(highs, key=lambda r: r["p"], reverse=True)[:5]

    # 5-3. 지표단지 회전율
    d_1y = (today - timedelta(days=365)).strftime("%Y%m%d")
    d_3m = months_ago(today, 3).strftime("%Y%m%d")
    by_district = defaultdict(list)
    for t in trades:
        by_district[t["d"]].append(t)

    groups = []
    total_hh = total_1y = total_3m = 0
    for district, apts in INDICATOR_COMPLEXES.items():
        items = []
        for apt in apts:
            kws = [normalize(k) for k in apt.get("keywords", [apt["name"]])]
            matched = [t for t in by_district.get(district, []) if any(k in normalize(t["n"]) for k in kws)]
            c1 = sum(1 for t in matched if d_1y < t["dt"] <= today_s)
            c3 = sum(1 for t in matched if d_3m < t["dt"] <= today_s)
            hh = apt["households"]
            items.append({
                "name": apt["name"], "households": hh,
                "c1": c1, "r1": c1 / hh * 100,
                "c3": c3, "r3": c3 / hh * 100,
            })
            total_hh += hh
            total_1y += c1
            total_3m += c3
        groups.append({"district": district, "items": items})

    all_items = [i for g in groups for i in g["items"]]
    max_r1 = max([i["r1"] for i in all_items] + [0.01])
    max_r3 = max([i["r3"] for i in all_items] + [0.01])
    for i in all_items:
        i["w1"] = round(i["r1"] / max_r1 * 100, 1)
        i["w3"] = round(i["r3"] / max_r3 * 100, 1)
        # 3개월 거래를 연환산했을 때 1년 대비 증감 (±15% 이상만 표시)
        annual = i["c3"] * 4
        i["trend"] = "up" if i["c1"] and annual >= i["c1"] * 1.15 else (
            "down" if i["c1"] and annual <= i["c1"] * 0.85 else "")

    best = max(all_items, key=lambda i: i["r1"]) if all_items else None
    hot = max(all_items, key=lambda i: i["r3"]) if all_items else None
    indicator = {
        "groups": groups,
        "count": len(all_items),
        "households": total_hh,
        "c1": total_1y, "r1": total_1y / total_hh * 100 if total_hh else 0,
        "c3": total_3m, "r3": total_3m / total_hh * 100 if total_hh else 0,
        "best": best, "hot": hot,
        "period_1y": f"{d_1y[2:4]}.{d_1y[4:6]}.{d_1y[6:]}~",
        "period_3m": f"{d_3m[2:4]}.{d_3m[4:6]}.{d_3m[6:]}~",
    }

    return {
        "date_label": today.strftime("%y.%m.%d"),
        "today_title": today_title,
        "today_note": today_note,
        "today_cnt": len(today_set),
        "high_cnt": len(highs),
        "high_ratio": round(len(highs) / len(today_set) * 100, 1) if today_set else 0,
        "top10": top10,
        "high5": high5,
        "indicator": indicator,
    }


def updated_high_prices(prior_high, trades):
    hp = dict(prior_high)
    for t in trades:
        k = price_key(t)
        if t["p"] > hp.get(k, 0):
            hp[k] = t["p"]
    return hp


# ==========================================
# 6. HTML 생성
# ==========================================
def render(context, out_path):
    env = Environment(loader=FileSystemLoader("templates"), autoescape=True)
    html = env.get_template("report_template.html").render(context)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ {out_path} 생성 완료")


# ==========================================
# 7. 예시 데이터 (--demo)
# ==========================================
DEMO_1Y = {
    "삼익비치": 42, "남천자이": 18, "남천더샵프레스티지": 11, "해운대자이2차1단지": 16,
    "더샵센텀파크1차": 31, "대연힐스테이트푸르지오": 35, "더비치푸르지오써밋": 19,
    "동래래미안아이파크": 58, "사직롯데캐슬더클래식": 14, "레이카운티": 72,
    "연산롯데캐슬골드포레": 21, "삼한골든뷰센트럴파크": 17, "래미안장전": 28,
    "명지더샵퍼스트월드3단지": 24, "화명롯데캐슬카이저": 65, "사상중흥S-클래스그랜드센트럴": 22,
    "힐스테이트사하역": 19, "두산위브더제니스하버시티": 29, "대신푸르지오2차": 10,
    "봉래에일린의뜰": 15, "일광자이푸르지오": 20,
}


def demo_data(today):
    rnd = random.Random(42)
    today_s = today.strftime("%Y%m%d")
    trades = []

    def add(d, u, n, a, f, p, dt, seen=""):
        trades.append({"id": f"{len(trades)}", "d": d, "u": u, "n": n, "s": "", "a": a,
                       "f": str(f), "p": p, "dt": dt, "seen": seen})

    # 지표단지: 1년 거래를 예시 건수만큼 분산 생성
    for district, apts in INDICATOR_COMPLEXES.items():
        for apt in apts:
            n = DEMO_1Y.get(apt["name"], 10)
            recent_bias = rnd.uniform(0.6, 1.5)
            for _ in range(n):
                days = int(rnd.random() ** recent_bias * 360)
                dt = (today - timedelta(days=days + 1)).strftime("%Y%m%d")
                add(district, "", apt["name"], 84.9, rnd.randint(3, 30), rnd.randint(40000, 90000), dt)

    # 오늘 신규 공개분 (과거 최고가 기록 + 신규 거래)
    sample = [
        ("해운대구", "우동", "현대베네시티", 169.183, 19, 220000, 200000),
        ("남구", "용호동", "더블유", 123.691, 31, 186000, 200000),
        ("수영구", "남천동", "남천자이", 84.985, 14, 137000, 156000),
        ("연제구", "거제동", "레이카운티(2단지)", 84.982, 33, 122000, 128800),
        ("동래구", "사직동", "사직롯데캐슬더클래식", 84.975, 28, 116000, 134000),
        ("해운대구", "우동", "해운대자이2차(1단지)", 84.94, 22, 113000, 105000),
        ("수영구", "광안동", "광안자이", 84.97, 17, 98000, 102000),
        ("동래구", "명륜동", "명륜자이", 84.99, 12, 93500, 89000),
        ("연제구", "거제동", "레이카운티(1단지)", 59.987, 16, 88000, 85500),
        ("부산진구", "범천동", "삼한골든뷰센트럴파크", 84.96, 25, 76000, 79000),
        ("부산진구", "연지동", "래미안어반파크", 84.98, 20, 74000, 80000),
        ("강서구", "명지동", "명지더샵퍼스트월드3단지", 84.95, 9, 61000, 58500),
    ]
    for i, (d, u, n, a, f, p, prev) in enumerate(sample):
        add(d, u, n, a, f + 3, prev, (today - timedelta(days=200)).strftime("%Y%m%d"))
        dt = (today - timedelta(days=3 + i * 2)).strftime("%Y%m%d")
        add(d, u, n, a, f, p, dt, seen=today_s)
    for _ in range(92):
        dt = (today - timedelta(days=rnd.randint(2, 30))).strftime("%Y%m%d")
        add("북구", "화명동", "기타단지", 59.9, 5, rnd.randint(15000, 45000), dt, seen=today_s)
    return trades


# ==========================================
# 8. 메인
# ==========================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true", help="DB 전체 재수집")
    ap.add_argument("--demo", action="store_true", help="예시 데이터로 렌더링")
    ap.add_argument("--out", default=None, help="출력 HTML 경로")
    args = ap.parse_args()

    now = datetime.now(KST)

    if args.demo:
        ctx = build_report(demo_data(now), {}, now, bootstrap=False)
        ctx["notice"] = "예시 데이터로 생성된 미리보기입니다."
        render(ctx, args.out or "demo.html")
        return

    db = load_db()
    prior_high = {} if args.rebuild else dict(db.get("high_prices", {}))
    errors = []
    if MOLIT_API_KEY:
        print("🔍 국토교통부 실거래가 수집 시작...")
        bootstrap, errors = update_db(db, now, rebuild=args.rebuild)
        print(f"✅ DB 거래 {len(db['trades']):,}건 (실패 {len(errors)}건)")
    else:
        print("⚠️ MOLIT_API_KEY 가 없어 기존 DB 로만 리포트를 만듭니다.")
        bootstrap = not any(t.get("seen") for t in db["trades"])

    ctx = build_report(db["trades"], prior_high, now, bootstrap)
    if not db["trades"]:
        ctx["notice"] = "실거래 데이터가 없습니다. API 키 승인 상태를 확인해 주세요."
    elif errors:
        ctx["notice"] = f"일부 지역 수집 실패 {len(errors)}건 — 이전 데이터로 대체되었습니다."

    db["high_prices"] = updated_high_prices(prior_high, db["trades"])
    if MOLIT_API_KEY:
        save_db(db)
    render(ctx, args.out or "index.html")


if __name__ == "__main__":
    main()
