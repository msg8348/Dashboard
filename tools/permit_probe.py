"""건축HUB 건축인허가정보 API 응답 확인용 (베뉴브 해운대: 부산 해운대구 우동 1074)."""
import json
import os
import sys

import requests

KEY = requests.utils.unquote(os.environ.get("MOLIT_API_KEY", ""))
ADDR, BUN, JI = (sys.argv[1:4] + ["", "", ""])[:3] if len(sys.argv) > 1 else ("부산광역시 해운대구 우동", "1074", "0000")


def get(url, params):
    try:
        r = requests.get(url, params={"serviceKey": KEY, **params}, timeout=(10, 60))
    except requests.RequestException as e:
        return None, str(e)
    return r, r.text


# 1) 법정동코드
r, t = get("https://apis.data.go.kr/1741000/StanReginCd/getStanReginCdList",
           {"pageNo": 1, "numOfRows": 10, "type": "json", "locatadd_nm": ADDR})
print("StanReginCd", getattr(r, "status_code", None), t[:400])
code = ""
try:
    rows = next(p["row"] for p in r.json()["StanReginCd"] if "row" in p)
    code = next(x["region_cd"] for x in rows if x["locatadd_nm"].strip() == ADDR)
except Exception as e:
    print("법정동코드 찾기 실패", e)
print("법정동코드", code)
sig, bjd = code[:5], code[5:10]

bases = ["https://apis.data.go.kr/1613000/ArchPmsHubService", "https://apis.data.go.kr/1613000/ArchPmsService_v2",
         "https://apis.data.go.kr/1613000/ArchPmsService"]
ops = ["getApBasisOulnInfo", "getApDongOulnInfo", "getApHoOulnInfo", "getApHoExposPubuseAreaInfo", "getApHsTpInfo",
       "getApFlrOulnInfo", "getApPklotInfo"]
p = {"sigunguCd": sig, "bjdongCd": bjd, "platGbCd": "0", "bun": BUN.zfill(4), "ji": (JI or "0").zfill(4),
     "numOfRows": 100, "pageNo": 1, "_type": "json"}
for b in bases:
    for op in ops:
        r, t = get(f"{b}/{op}", p)
        st = getattr(r, "status_code", None)
        head = " ".join(t.split())[:160]
        items, total = [], None
        try:
            j = r.json()
            body = j["response"]["body"]
            total = body.get("totalCount")
            it = (body.get("items") or {}).get("item") or []
            items = it if isinstance(it, list) else [it]
        except Exception:
            pass
        print(f"\n### {b.split('/')[-1]}/{op} → HTTP {st} · total {total}")
        if items:
            print("keys:", list(items[0].keys()))
            for x in items[:3]:
                print(json.dumps(x, ensure_ascii=False)[:700])
        else:
            print(head)
