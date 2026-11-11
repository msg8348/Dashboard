name: INIT REAL ESTATE DB (1 YEAR)

on:
  workflow_dispatch:

jobs:
  build-db:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - name: 저장소 체크아웃
        uses: actions/checkout@v4

      - name: 파이썬 3.10 설치
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: 의존성 패키지 설치
        run: |
          python -m pip install --upgrade pip
          pip install requests

      - name: 부산 1년치 아파트 및 분양권 실거래가(날짜 포함) 데이터 수집
        env:
          MOLIT_API_KEY: ${{ secrets.MOLIT_API_KEY }}
        run: |
          cat << 'EOF' > run_init.py
          import os
          import json
          import re
          import time
          import xml.etree.ElementTree as ET
          from datetime import datetime, timedelta, timezone
          import requests

          MOLIT_API_KEY = os.environ.get("MOLIT_API_KEY", "")

          # 부산 16개 구·군 법정동 시군구코드
          BUSAN_LAWD_CD = {
              "중구": "26110", "서구": "26140", "동구": "26170", "영도구": "26200",
              "부산진구": "26230", "동래구": "26260", "남구": "26290", "북구": "26320",
              "해운대구": "26350", "사하구": "26380", "금정구": "26410", "강서구": "26440",
              "연제구": "26470", "수영구": "26500", "사상구": "26530", "기장군": "26710"
          }

          def strip_html_tags(text):
              if not text:
                  return ""
              clean = re.sub(r"<[^>]*>", "", str(text))
              return clean.replace("&lt;", "").replace("&gt;", "").strip()

          # 1) 일반 아파트 매매 수집 (거래일자 포함)
          def fetch_apt_trades(lawd_cd, deal_ym, district_name):
              if not MOLIT_API_KEY:
                  return []

              url = "http://apis.data.go.kr/1613000/RTMSOBJSvc/getRTMSDataSvcAptTradeDev"
              params = {
                  "serviceKey": requests.utils.unquote(MOLIT_API_KEY),
                  "LAWD_CD": lawd_cd,
                  "DEAL_YMD": deal_ym,
                  "pageNo": "1",
                  "numOfRows": "2000"
              }
              
              trades = []
              for attempt in range(2):
                  try:
                      res = requests.get(url, params=params, timeout=30)
                      if res.status_code == 200:
                          root = ET.fromstring(res.text)
                          result_code = root.find(".//resultCode")
                          if result_code is not None and result_code.text != "00":
                              break

                          for item in root.findall(".//item"):
                              apt_name = strip_html_tags(item.findtext("aptNm") or item.findtext("단지") or item.findtext("아파트") or "")
                              price_str = (item.findtext("dealAmount") or item.findtext("거래금액") or "0").strip().replace(",", "")
                              price = int(price_str) if price_str.isdigit() else 0
                              area = (item.findtext("excluUseAr") or item.findtext("전용면적") or "0").strip()
                              day = (item.findtext("dealDay") or item.findtext("일") or "0").strip().zfill(2)
                              cancel_day = (item.findtext("cancellDealDay") or item.findtext("해제사유발생일") or "").strip()
                              
                              if cancel_day: # 해제된 거래 제외
                                  continue

                              if apt_name and price > 0:
                                  trades.append({
                                      "apt_name": apt_name,
                                      "area": area,
                                      "price": price,
                                      "deal_ymd": f"{deal_ym}{day}", # YYYYMMDD 날짜 표기
                                      "district": district_name,
                                      "type": "매매"
                                  })
                          break
                  except Exception as e:
                      time.sleep(1)
                      
              time.sleep(0.15)
              return trades

          # 2) 분양권/입주권 매매 수집 (거래일자 포함)
          def fetch_right_trades(lawd_cd, deal_ym, district_name):
              if not MOLIT_API_KEY:
                  return []

              url = "http://apis.data.go.kr/1613000/RTMSDataSvcAptLoaderAct/getRTMSDataSvcAptLoaderAct"
              params = {
                  "serviceKey": requests.utils.unquote(MOLIT_API_KEY),
                  "LAWD_CD": lawd_cd,
                  "DEAL_YMD": deal_ym,
                  "pageNo": "1",
                  "numOfRows": "2000"
              }
              
              trades = []
              for attempt in range(2):
                  try:
                      res = requests.get(url, params=params, timeout=30)
                      if res.status_code == 200:
                          root = ET.fromstring(res.text)
                          result_code = root.find(".//resultCode")
                          if result_code is not None and result_code.text != "00":
                              break

                          for item in root.findall(".//item"):
                              apt_name = strip_html_tags(item.findtext("untyAptNm") or item.findtext("aptNm") or item.findtext("buildingNm") or item.findtext("단지명") or "")
                              price_str = (item.findtext("dealAmount") or item.findtext("거래금액") or "0").strip().replace(",", "")
                              price = int(price_str) if price_str.isdigit() else 0
                              area = (item.findtext("excluUseAr") or item.findtext("전용면적") or "0").strip()
                              day = (item.findtext("dealDay") or item.findtext("일") or "0").strip().zfill(2)
                              cancel_day = (item.findtext("cancellDealDay") or item.findtext("해제사유발생일") or "").strip()
                              
                              if cancel_day:
                                  continue

                              if apt_name and price > 0:
                                  trades.append({
                                      "apt_name": f"[분양권]{apt_name}",
                                      "area": area,
                                      "price": price,
                                      "deal_ymd": f"{deal_ym}{day}", # YYYYMMDD 날짜 표기
                                      "district": district_name,
                                      "type": "분양권"
                                  })
                          break
                  except Exception as e:
                      time.sleep(1)
                      
              time.sleep(0.15)
              return trades

          def main():
              kst = timezone(timedelta(hours=9))
              now = datetime.now(kst)
              
              # 최근 12개월(1년) 년월 리스트 생성
              months = []
              for i in range(12):
                  year = now.year
                  month = now.month - i
                  while month <= 0:
                      month += 12
                      year -= 1
                  months.append(f"{year}{month:02d}")
                  
              print(f"🚀 부산광역시 최근 1년치({months[-1]} ~ {months[0]}) 아파트/분양권 수집 시작!")
              
              all_trades = []
              high_prices = {}
              
              for ym in months:
                  print(f"📅 {ym} 데이터 수집 중...")
                  for district, lawd_cd in BUSAN_LAWD_CD.items():
                      # 아파트 매매 수집
                      apt_list = fetch_apt_trades(lawd_cd, ym, district)
                      # 분양권/입주권 수집
                      right_list = fetch_right_trades(lawd_cd, ym, district)
                      
                      for t in apt_list + right_list:
                          all_trades.append(t)
                          
                          # 최고가 저장 (단지명_면적 기준)
                          key = f"{t['apt_name']}_{t['area']}"
                          if t['price'] > high_prices.get(key, 0):
                              high_prices[key] = t['price']

              # 동일 거래건 중복 제거 (단지명 + 면적 + 거래일자 + 금액 기준)
              unique_trades = {f"{t['apt_name']}_{t['area']}_{t['deal_ymd']}_{t['price']}": t for t in all_trades}.values()

              db_data = {
                  "trades": list(unique_trades),
                  "high_prices": high_prices
              }

              if len(db_data['trades']) > 0:
                  os.makedirs("data", exist_ok=True)
                  with open("data/real_estate_db.json", "w", encoding="utf-8") as f:
                      json.dump(db_data, f, ensure_ascii=False, indent=2)
                  print(f"🎉 부산 1년치 데이터 수집 완료! (총 {len(db_data['trades'])}건 거래 및 {len(high_prices)}개 단지/평형 최고가 기록)")
              else:
                  print("⚠️ 수집된 거래 데이터가 없습니다. API 인증키 승인 상태를 확인하세요.")

          if __name__ == "__main__":
              main()
          EOF
          python run_init.py
          rm run_init.py

      - name: Git 자동 커밋 및 푸시
        run: |
          git config --local user.email "github-actions[bot]@users.noreply.github.com"
          git config --local user.name "github-actions[bot]"
          if [ -f "data/real_estate_db.json" ]; then
            git add data/real_estate_db.json
            git diff --quiet && git diff --staged --quiet || (git commit -m "data: 최근 1년치 부산 실거래가(날짜포함) DB 최초 구축 [skip ci]" && git push)
          else
            echo "수집된 데이터가 없어서 Git 커밋을 건너뜁니다."
          fi
