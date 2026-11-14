"""카카오 로컬 API 응답 확인: 주소→좌표, 근처 초등학교·지하철(출구)·버스정류장."""
import json
import os
import sys

import requests

KEY = os.environ.get("KAKAO_API_KEY", "")
H = {"Authorization": f"KakaoAK {KEY}"}
API = "https://dapi.kakao.com/v2/local"
CASES = [("부산 사하구 하단동 1217-1", "하단동에스케이뷰"), ("부산 남구 대연동 1886", "더비치푸르지오써밋"),
         ("부산 금정구 장전동 745", "래미안장전")]


def get(path, **p):
    r = requests.get(f"{API}/{path}", headers=H, params=p, timeout=20)
    print(f"  GET {path} {p.get('query', p.get('category_group_code', ''))} → {r.status_code}")
    if r.status_code != 200:
        print("  ", r.text[:300])
        return []
    return r.json().get("documents", [])


print("키 길이", len(KEY))
for addr, name in CASES:
    print(f"\n### {name} ({addr})")
    d = get("search/address.json", query=addr)
    if not d:
        d = get("search/keyword.json", query=f"{addr.split()[2]} {name}")
    if not d:
        continue
    x, y = d[0]["x"], d[0]["y"]
    print("  좌표", x, y, "| 첫 결과", json.dumps(d[0], ensure_ascii=False)[:300])
    k = get("search/keyword.json", query=name, x=x, y=y, radius=500, sort="distance")
    print("  단지 키워드:", [(z["place_name"], z["category_name"], z["distance"], z["id"]) for z in k[:3]])
    for code in ("SC4", "SW8"):
        r = get("search/category.json", category_group_code=code, x=x, y=y, radius=2000, sort="distance")
        print("  ", code, [(z["place_name"], z["category_name"].split(" > ")[-1], z["distance"]) for z in r[:4]])
    for q in ("출구", "버스정류장", "정류장"):
        r = get("search/keyword.json", query=q, x=x, y=y, radius=1000, sort="distance")
        print("  ", q, [(z["place_name"], z["category_name"], z["distance"]) for z in r[:4]])
