import os
from datetime import datetime, timedelta, timezone
from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

INDICATOR_COMPLEXES = {
    "수영구": [
        {"name": "삼익비치", "households": 3060, "deals": 42},
        {"name": "남천자이", "households": 913, "deals": 18},
        {"name": "남천더샵프레스티지", "households": 975, "deals": 11},
    ],
    "해운대구": [
        {"name": "해운대자이2차1단지", "households": 813, "deals": 16},
        {"name": "더샵센텀파크1차", "households": 2752, "deals": 31},
    ],
    "남구": [
        {"name": "대연힐스테이트푸르지오", "households": 2304, "deals": 35},
        {"name": "더비치푸르지오써밋", "households": 1384, "deals": 19},
    ],
    "동래구": [
        {"name": "동래래미안아이파크", "households": 3853, "deals": 58},
        {"name": "사직롯데캐슬더클래식", "households": 1064, "deals": 14},
    ],
    "연제구": [
        {"name": "레이카운티", "households": 4470, "deals": 72},
        {"name": "연산롯데캐슬골드포레", "households": 1450, "deals": 21},
    ],
    "부산진구": [
        {"name": "삼한골든뷰센트럴파크", "households": 1272, "deals": 17},
    ],
    "금정구": [
        {"name": "래미안장전", "households": 1938, "deals": 28},
    ],
    "강서구": [
        {"name": "명지더샵퍼스트월드3단지", "households": 1530, "deals": 24},
    ],
    "북구": [
        {"name": "화명롯데캐슬카이저", "households": 5239, "deals": 65},
    ],
    "사상구": [
        {"name": "사상중흥S-클래스그랜드센트럴", "households": 1508, "deals": 22},
    ],
    "사하구": [
        {"name": "힐스테이트사하역", "households": 1314, "deals": 19},
    ],
    "동구": [
        {"name": "두산위브더제니스하버시티", "households": 2040, "deals": 29},
    ],
    "서구": [
        {"name": "대신푸르지오2차", "households": 815, "deals": 10},
    ],
    "영도구": [
        {"name": "봉래에일린의뜰", "households": 1216, "deals": 15},
    ],
    "기장군": [
        {"name": "일광자이푸르지오", "households": 1547, "deals": 23},
    ],
}

def generate_web_dashboard(context_data, output_html_path="index.html", output_image_path="busan_report.png"):
    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template("report_template.html")
    html_content = template.render(context_data)
    
    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"✅ index.html 생성 완료: {output_html_path}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 800, "height": 1600}, device_scale_factor=2)
        page.goto(f"file://{os.path.abspath(output_html_path)}")
        page.locator(".container").screenshot(path=output_image_path)
        browser.close()
    print(f"✅ 이미지 캡처 완료: {output_image_path}")

def main():
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    date_label = now.strftime("%y.%m.%d")

    today_cnt = 104
    high_cnt = 2
    avg_3m = "1,555"

    top10_list = [
        {"apt_name": "현대베네시티", "price": "22억"},
        {"apt_name": "더블유", "price": "18.6억"},
        {"apt_name": "남천자이", "price": "13.7억"},
        {"apt_name": "레이카운티(2단지)", "price": "12.2억"},
        {"apt_name": "사직롯데캐슬더클래식", "price": "11.6억"},
        {"apt_name": "센텀파크1차", "price": "11.2억"},
        {"apt_name": "래미안장전", "price": "10.5억"},
        {"apt_name": "대연힐스테이트푸르지오", "price": "9.8억"},
        {"apt_name": "광안자이", "price": "9.5억"},
        {"apt_name": "삼익비치타운", "price": "9.2억"},
    ]

    high5_list = [
        {"apt_name": "레이카운티(1단지)", "price": "8.8억 (+2,500만)"},
        {"apt_name": "현대베네시티", "price": "22억 (+2,000만)"},
    ]

    indicator_data = {}
    for district, apts in INDICATOR_COMPLEXES.items():
        indicator_data[district] = []
        for apt in apts:
            turnover = round((apt["deals"] / apt["households"]) * 100, 2)
            indicator_data[district].append({
                "name": apt["name"],
                "households": f"{apt['households']:,}",
                "deals": apt["deals"],
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
