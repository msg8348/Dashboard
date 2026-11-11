import os
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import requests

# 🔑 발급받으신 국토교통부 API 키를 입력하세요 (Decoding/Encoding 상관없음)
MOLIT_API_KEY = "여기에_발급받으신_인증키_입력"

BUSAN_LAWD_CD = {
    "중구": "26110", "서구": "26140", "동구": "26170", "영도구": "26200",
    "부산진구": "26230", "동래구": "26260", "남구": "26290", "북구": "26320",
    "해운대구": "26350", "사하구": "26380", "금정구": "26410", "강서구": "26440",
    "연제구": "26470", "수영구": "26500", "사상구": "26530", "기장군": "26710"
}

def fetch_month_data(lawd_cd, deal_ym):
    url = "http://apis.data.go.kr/1613000/RTMSOBJSvc/getRTMSDataSvcAptTradeDev"
    params = {
        "serviceKey": requests.utils.unquote(MOLIT_API_KEY),
        "LAWD_CD": lawd_cd,
        "DEAL_YMD": deal_ym,
        "pageNo": "1",
        "numOfRows": "2000"
    }
    trades = []
    try:
        res = requests.get(url, params=params, timeout=15)
        if res.status_code == 200:
            root = ET.fromstring(res.text)
            for item in root.findall(".//item"):
                apt_name = (item.findtext("단지", "") or item.findtext("아파트", "")).strip()
                price_str = item.findtext("거래금액", "0").strip().replace(",", "")
                price = int(price_str) if price_str.isdigit() else 0
                area = item.findtext("전용면적", "0").strip()
                day = item.findtext("일", "0").strip().zfill(2)
                cancel_day = item.findtext("해제사유발생일", "").strip()
                
                if cancel_day: # 해제건 제외
                    continue

                if apt_name and price > 0:
                    trades.append({
                        "apt_name": apt_name,
                        "area": area,
                        "price": price,
                        "deal_ymd": f"{deal_ym}{day}"
                    })
    except Exception as e:
        print(f"⚠️ 에러 ({lawd_cd}, {deal_ym}): {e}")
    return trades

def build_initial_db():
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    
    # 최근 12개월(1년) 년월 리스트 생성
    months = []
    for i in range(12):
        # 현재 월부터 1개월씩 차감
        year = now.year
        month = now.month - i
        while month <= 0:
            month += 12
            year -= 1
        months.append(f"{year}{month:02d}")
        
    print(f"🚀 최근 1년치 데이터 수집 시작 대상 월: {months}")
    
    all_trades = []
    high_prices = {}
    
    for ym in months:
        print(f"📅 {ym} 데이터 수집 중...")
        for district, lawd_cd in BUSAN_LAWD_CD.items():
            t_list = fetch_month_data(lawd_cd, ym)
            for t in t_list:
                t["district"] = district
                all_trades.append(t)
                
                # 역대 최고가 기록
                key = f"{t['apt_name']}_{t['area']}"
                if t['price'] > high_prices.get(key, 0):
                    high_prices[key] = t['price']

    # 중복 제거 (동일 거래건)
    unique_trades = {f"{t['apt_name']}_{t['area']}_{t['deal_ymd']}_{t['price']}": t for t in all_trades}.values()

    db_data = {
        "trades": list(unique_trades),
        "high_prices": high_prices
    }

    os.makedirs("data", exist_ok=True)
    with open("data/real_estate_db.json", "w", encoding="utf-8") as f:
        json.dump(db_data, f, ensure_ascii=False, indent=2)
        
    print(f"🎉 성공적으로 최근 1년치 데이터베이스가 생성되었습니다! (총 {len(db_data['trades'])}건 거래 수집 완료)")

if __name__ == "__main__":
    build_initial_db()
