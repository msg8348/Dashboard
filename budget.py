"""나의 예산 — 대출 규제 기본값(RULES) + 예산 맞춤 추천용 단지 목록(site/bud/{시도}.json).

RULES 는 일반 무주택(또는 1주택 처분 조건) 시민 · 은행권 기준의 기본값이다. 정책이 바뀌면 여기만 고친다.
(26.11 기준 조사 초안: 금융위 6.27·10.15 대책, 스트레스 DSR, 지방세 — 화면에 '실제 한도는 은행 심사에 따라 다름' 안내)
"""
import json
import os
import statistics
from collections import defaultdict
from datetime import timedelta

RULES = {
    "asof": "26.11",
    "dsr": 40,                                   # 은행권 차주 DSR (%)
    "regions": {                                 # LTV(%) · 생애최초 LTV(%) · 스트레스 금리(%p) · 금액 상한 [[시가 이하(만원), 상한(만원)]...]
        "reg": {"name": "규제지역", "ltv": 40, "ltv1": 70, "stress": 3.0, "cap": [[150000, 60000], [250000, 40000], [10**9, 20000]]},
        "cap": {"name": "수도권", "ltv": 70, "ltv1": 70, "stress": 3.0, "cap": [[10**9, 60000]]},
        "local": {"name": "지방", "ltv": 70, "ltv1": 80, "stress": 0.75, "cap": []},
    },
    "acq_first_cut": 200,                        # 생애최초 취득세 감면 (만원, 12억 이하)
    "acq_first_max": 120000,
    "gift_ded": 5000,                            # 직계존속 증여재산공제 (만원, 10년 합산)
    "gift_ded_marry": 10000,                     # 혼인·출산 추가 공제
    "brands": ["래미안", "힐스테이트", "디에이치", "푸르지오", "써밋", "e편한세상", "이편한세상", "아크로", "자이",
               "더샵", "롯데캐슬", "르엘", "SK뷰", "SKVIEW", "에스케이뷰", "아이파크", "IPARK"],
}
SIDO_REGION = {"11": "reg", "41": "cap", "28": "cap"}   # 시도 기본 지역 구분 (서울 전역 규제, 경기·인천 수도권, 나머지 지방)


def _ty(a):
    ai = int(a)
    return 59 if ai == 59 else 74 if 70 <= ai <= 77 else 84 if ai == 84 else 0


def build(site, sd, sdir, sale, cinfo, l2_of, l2_name, apt_pages, pcache, today):
    """최근 6개월 매매로 단지·평형별 중간값 → site/bud/{sdir}.json"""
    d6 = (today - timedelta(days=183)).strftime("%Y%m%d")
    by, meta = defaultdict(list), {}
    for t in sale:
        s = t.get("s")
        if not s or s not in apt_pages or str(t["dt"]) < d6:
            continue
        ty = _ty(t["a"])
        if not ty:
            continue
        by[(s, ty)].append(t)
        if s not in meta:
            hh, ap = cinfo(t)
            yr = int(ap[:4]) if ap and str(ap)[:4].isdigit() else (int(t["by"]) if str(t.get("by", "")).isdigit() else 0)
            p = pcache.get(s) or {}
            sc = (p.get("as") or [p.get("sc")])[0]   # 배정 초등학교 우선, 없으면 가까운 초등학교
            meta[s] = {"n": t["n"], "g": l2_name.get(l2_of.get(t.get("c")), (t.get("d") or "").split()[-1]), "d": t.get("u", ""),
                       "y": yr, "h": hh or 0, "sc": sc, "st": p.get("st"), "p": f"{sdir}/apt/{s}.html", "t": {}}
    for (s, ty), ts in by.items():
        ts.sort(key=lambda x: -int(x["dt"]))
        meta[s]["t"][str(ty)] = [round(statistics.median(x["p"] for x in ts)), len(ts),
                                 [[str(x["dt"]), x["p"], x.get("f", "")] for x in ts[:3]]]
    os.makedirs(os.path.join(site, "bud"), exist_ok=True)
    with open(os.path.join(site, "bud", f"{sdir}.json"), "w", encoding="utf-8") as f:
        json.dump({"g": [l["name"] for l in sd["l2"]] if len(sd["l2"]) > 1 else [], "a": list(meta.values()),
                   "region": SIDO_REGION.get(sd["key"], "local")}, f, ensure_ascii=False, separators=(",", ":"))
