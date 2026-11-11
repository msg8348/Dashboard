import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import requests
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

# ==========================================
# 1. 설정 및 부산 16개 구/군 법정동 시군구코드 (5자리)
# ==========================================
MOLIT_API_KEY = os.environ.get("MOLIT_API_KEY", "")

BUSAN_LAWD_CD = {
    "중구": "26110", "서구": "26140", "동구": "26170", "영도구": "26200",
    "부산진구": "26230", "동래구": "26260", "남구": "26290", "북구": "26320",
    "해운대구": "26350", "사하구": "26380", "금정구": "26410", "강서구": "26440",
    "연제구": "26470", "수영구": "26500", "사상구": "26530", "기장군": "26710"
}

# 22개 주요 지표단지 설정
INDICATOR_COMPLEXES = {
    "수영구": [
        {"name": "삼익비치", "households": 3060},
        {"name": "남천자이", "households": 913},
        {"name": "남천더샵프레스티지", "households": 975},
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
        {"name": "명지더샵퍼스트월드3단지", "households": 1530},
    ],
    "북구": [
        {"name": "화명롯데캐슬카이저", "households": 5239},
    ],
    "사상구": [
        {"name": "사상중흥S-클래스그랜드센트럴", "households": 1508},
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
        {"name": "봉래에일린의뜰", "households": 1216},
    ],
    "기장군": [
        {"name": "일광자이푸르지오", "households": 1547},
    ],
}


# ==========================================
# 2. 국토교통부 실거래가 API 수집
# ==========================================
def fetch_molit_real_estate_data(lawd_cd, deal_ym):
    """국토교통부 아파트매매 실거래 상세 자료 API 호출"""
    if not MOLIT_API_KEY:
        return []

    url = "http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptTradeDev"
    params = {
        "serviceKey": requests.utils.unquote(MOLIT_API_KEY),
        "LAWD_CD": lawd_cd,
        "DEAL_YMD": deal_ym,
        "numOfRows": "1000"
    }
    
    trades = []
    try:
        res = requests.get(url, params=params, timeout=12)
        if res.status_code == 200:
            root = ET.fromstring(res.text)
            items = root.findall(".//item")
            for item in items:
                apt_name = (item.findtext("단지", "") or item.findtext("아파트", "")).strip()
                price_str = item.findtext("거래금액", "0").strip().replace(",", "")
                price = int(price_str) if price_str.isdigit() else 0
                day = item.findtext("일", "").strip()
                cancel_deal_day = item.findtext("해제사유발생일", "").strip()
                
                # 계약 해제건은 제외
                if cancel_deal_day:
                    continue

                if apt_name and price > 0:
                    trades.append({
                        "apt_name": apt_name,
                        "price": price,
                        "day": day,
                        "deal_ym": deal_ym
                    })
    except Exception as e:
        print(f"⚠️ API 수집 실패 (지역코드: {lawd_cd}, 조회월: {deal_ym}): {e}")
        
    return trades


# ==========================================
# 3. HTML 생성 및 Playwright 이미지 캡처
# ==========================================
def generate_web_dashboard(context_data, output_html_path="index.html", output_image_path="busan_report.png"):
    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template("report_template.html")
    html_content = template.render(context_data)
    
    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"✅ index.html 파일 생성 완료")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 800, "height": 1600}, device_scale_factor=2)
        page.goto(f"file://{os.path.abspath(output_html_path)}")
        page.locator(".container").screenshot(path=output_image_path)
        browser.close()
    print(f"✅ 이미지 캡처 완료")


# ==========================================
# 4. 메인 데이터 처리 및 계산 함수
# ==========================================
def main():
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    date_label = now.strftime("%y.%m.%d")
    
    current_ym = now.strftime("%Y%m")
    first_day_this_month = now.replace(day=1)
    last_month = first_day_this_month - timedelta(days=1)
    last_ym = last_month.strftime("%Y%m")

    print(f"🔍 국토교통부 실거래가 데이터 실시간 조회 중 ({current_ym}, {last_ym})...")
    
    all_trades = []
    # 부산 16개 구/군 데이터 수집
    for district, lawd_cd in BUSAN_LAWD_CD.items():
        all_trades.extend(fetch_molit_real_estate_data(lawd_cd, current_ym))
        all_trades.extend(fetch_molit_real_estate_data(lawd_cd, last_ym))

    # 데이터 수집 성공 시 실제 거래 정보 추출
    if all_trades:
        print(f"✅ 총 {len(all_trades)}건의 실거래가 데이터를 수집했습니다.")
        
        today_str = str(now.day)
        today_trades = [t for t in all_trades if t["deal_ym"] == current_ym and t["day"] == today_str]
        today_cnt = len(today_trades)
        
        # 1. 금액순 최고가 Top 10
        sorted_trades = sorted(all_trades, key=lambda x: x["price"], reverse=True)
        top10_list = []
        for t in sorted_trades[:10]:
            p = t['price']
            price_str = f"{p // 10000}억 {p % 10000:,}만" if p >= 10000 else f"{p:,}만"
            price_str = price_str.replace(" 0만", "")
            top10_list.append({"apt_name": t["apt_name"], "price": price_str})

        # 2. 최근 거래가 상위 Top 5
        high5_list = []
        for t in sorted_trades[:5]:
            p = t['price']
            price_str = f"{p // 10000}억 {p % 10000:,}만" if p >= 10000 else f"{p:,}만"
            price_str = price_str.replace(" 0만", "")
            high5_list.append({"apt_name": t["apt_name"], "price": price_str})
            
        high_cnt = len(high5_list)
        avg_3m = f"{len(all_trades) // 2:,}"
    else:
        # API 동기화 지연(발급 직후 1~2시간) 시 표시될 임시 안내 데이터
        print("⚠️ 국토부 API 응답이 없거나 동기화 중입니다. 임시 데이터를 표시합니다.")
        today_cnt = 0
        high_cnt = 0
        avg_3m = "0"
        top10_list = [{"apt_name": "API 수집 준비 중입니다", "price": "-"}]
        high5_list = [{"apt_name": "API 수집 준비 중입니다", "price": "-"}]

    # 3. 22개 지표단지 거래건수 및 회전율 계산
    indicator_data = {}
    for district, apts in INDICATOR_COMPLEXES.items():
        indicator_data[district] = []
        for apt in apts:
            matched_deals = sum(1 for t in all_trades if apt["name"] in t["apt_name"])
            turnover = round((matched_deals / apt["households"]) * 100, 2)
            indicator_data[district].append({
                "name": apt["name"],
                "households": f"{apt['households']:,}",
                "deals": matched_deals,
                "turnover": turnover
            })

    context_data = {
        "date_label": date_label,
        "today_cnt": today_cnt,
        "high_cnt": high_cnt,
        "avg_3m": avg_3m,
        "top10_list": top10_list,
        "high5_list": high5_list,
        "indicator_data": indicator_data
    }

    generate_web_dashboard(context_data)

if __name__ == "__main__":
    main()
