"""poi.find 시험 (카카오 + TAGO 버스)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
import poi

r = requests.get(poi.TAGO, params={"serviceKey": poi.MOLIT, "gpsLati": 35.1376, "gpsLong": 129.0829, "_type": "json", "numOfRows": 5}, timeout=15)
print("TAGO", r.status_code, r.text[:400])
for a, n in [("부산 사하구 하단동 1217-1", "하단동에스케이뷰"), ("부산 남구 대연동 1886", "더비치푸르지오써밋"),
             ("부산 금정구 장전동 745", "래미안장전"), ("부산 기장군 정관읍 용수리 1387", "정관동일스위트1차")]:
    print(n, poi.find(a, n))
