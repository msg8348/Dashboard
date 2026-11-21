"""주간변동률 메뉴 — 한국부동산원 전국주택가격동향(주간) 아파트 매매·전세가격지수 → site/weekly.json

R-ONE 부동산통계정보시스템 Open API (인증키: 환경변수 REB_API_KEY)
    통계표 목록  : /SttsApiTbl.do      → 이름에 '주간'·'아파트'·'매매가격지수'/'전세가격지수' 가 들어간 통계표를 찾음
    통계표 자료  : /SttsApiTblData.do  → 지역(CLS_FULLNM)·시점(WRTTIME_IDTFR_ID)·값(DTA_VAL)
지수로 이번 주 변동률(전주 대비)과 연초 대비 누적 변동률을 계산한다.
키가 없거나 받기에 실패하면 저장본(store/weekly.json)을 쓰고, 그것도 없으면 빈 화면(준비 중).
응답 모양이 예상과 다를 수 있어 서비스별 첫 응답 요약(diag)을 저장본에 함께 남긴다.
"""
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime

import requests

BASE = "https://www.reb.or.kr/r-one/openapi"
KEY = os.environ.get("REB_API_KEY", "")
DIAG = {}
NAT = ("전국", "수도권", "지방")


def _get(op, **params):
    r = None
    for i in range(4):   # 한국부동산원 서버가 가끔 느려서 다시 시도
        try:
            r = requests.get(f"{BASE}/{op}", params=dict({"KEY": KEY, "Type": "json"}, **params), timeout=(15, 120))
            break
        except requests.RequestException:
            if i == 3:
                raise
            time.sleep(5 * (i + 1))
    j = r.json()
    body = j.get(op.replace(".do", "")) or []
    head = next((b["head"] for b in body if "head" in b), [])
    rows = next((b["row"] for b in body if "row" in b), [])
    total = next((h.get("list_total_count") for h in head if isinstance(h, dict) and "list_total_count" in h), 0)
    if op not in DIAG:
        DIAG[op] = {"status": r.status_code, "keys": list(j.keys())[:5], "total": total,
                    "row0": {k: str(v)[:40] for k, v in (rows[0].items() if rows else [])},
                    "raw": r.text[:300] if not rows else ""}
    return rows, int(total or 0)


def _find_tables():
    """주간(DTACYCLE_CD=WK) 통계표 중 '매매가격지수'·'전세가격지수' — 이름에 '아파트'가 있으면 그쪽을 먼저."""
    rows, total = _get("SttsApiTbl.do", pIndex=1, pSize=1000)
    wk = [r for r in rows if str(r.get("DTACYCLE_CD", "")).upper() == "WK" or "(주)" in str(r.get("STATBL_NM", ""))]
    DIAG["wk_tables"] = [f"{r.get('STATBL_ID')} {r.get('STATBL_NM')}" for r in wk][:60]
    found = {}
    for k, w in (("s", "매매가격지수"), ("j", "전세가격지수")):
        cand = [r for r in wk if w in str(r.get("STATBL_NM", "")).replace(" ", "")]
        cand.sort(key=lambda r: (0 if "아파트" in str(r.get("STATBL_NM", "")) else 1, len(str(r.get("STATBL_NM", "")))))
        if cand:
            found[k] = (cand[0].get("STATBL_ID"), cand[0].get("STATBL_NM"))
    DIAG["tables"] = {k: v[1] for k, v in found.items()}
    return {k: v[0] for k, v in found.items()}


def _series(tid, year):
    """{지역 전체이름: {시점: 지수}} — 올해와 작년 마지막 주만 (끝 쪽 페이지부터 읽음)."""
    _, total = _get("SttsApiTblData.do", STATBL_ID=tid, DTACYCLE_CD="WK", pIndex=1, pSize=1)
    pages = (total + 999) // 1000
    out = defaultdict(dict)
    for p in range(pages, 0, -1):
        rows, _ = _get("SttsApiTblData.do", STATBL_ID=tid, DTACYCLE_CD="WK", pIndex=p, pSize=1000)
        old = False
        for r in rows:
            t = str(r.get("WRTTIME_IDTFR_ID") or "")
            try:
                v = float(r.get("DTA_VAL"))
            except (TypeError, ValueError):
                continue
            name = str(r.get("CLS_FULLNM") or r.get("CLS_NM") or "")
            out[name][t] = v
            if t[:4] < str(year - 1):
                old = True
        if old:
            break
    return out


def _summarize(series, year):
    def chg(d):
        ts = sorted(d)
        if len(ts) < 2:
            return None, None, None
        now, prev = d[ts[-1]], d[ts[-2]]
        base = [t for t in ts if t[:4] < str(year)]
        ytd = (now / d[base[-1]] - 1) * 100 if base else None
        return ts[-1], (now / prev - 1) * 100, ytd
    nat, sido, sub, flat = {}, {}, defaultdict(list), []
    last = ""
    rows = []
    for full, d in series.items():
        t, w, y = chg(d)
        parts = [x for x in re.split(r"\s*>\s*", full or "") if x and x != "None"]
        if w is None or not parts:
            continue
        last = max(last, t)
        rows.append((parts, round(w, 2), round(y, 2) if y is not None else None))
    parents = {p for parts, _, _ in rows for p in parts[:-1]}   # 다른 지역의 상위(예: 수원시)면 잎이 아님
    for parts, w, y in rows:
        name = parts[-1]
        if name in NAT and len(parts) == 1:
            nat[name] = w
            continue
        rest = [x for x in parts if x not in NAT]
        if not rest:
            continue
        sd = rest[0]
        if len(rest) == 1:
            sido[sd] = w
            continue
        if re.search(r"(권|지역)$", name) or name in parents:   # 권역 묶음·상위 시는 빼고 맨 아래 시군구만
            continue
        par = rest[-2]
        if sd == "서울":
            lab = name
        elif par.endswith("시") and par != sd and name.endswith("구"):
            lab = f"{par[:-1]} {name}"            # 수원 영통구
        elif sd in ("부산", "대구", "인천", "광주", "대전", "울산"):
            lab = f"{sd} {name}"                   # 부산 강서구
        else:
            lab = name[:-1] if name.endswith("시") and len(name) > 2 else name   # 광명 · 익산 · 군은 그대로
        sub[sd].append([lab.replace(f"{sd} ", ""), w])   # 지도 칸 이름 (경기: 수원 영통구 · 광명)
        flat.append([lab, w, y])
    flat.sort(key=lambda x: -x[1])
    ytd = sorted([f for f in flat if f[2] is not None], key=lambda x: -x[2])
    return {"t": last, "nat": nat, "sido": sido, "sub": dict(sub),
            "up": [f[:2] for f in flat[:10]], "dn": [f[:2] for f in flat[::-1][:10]], "ytd": [[f[0], f[2]] for f in ytd[:5]]}


def build(site, store, now=None):
    now = now or datetime.now()
    path = os.path.join(store, "weekly.json")
    st = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
    fresh = st and st.get("fetched") == now.strftime("%Y%m%d")
    if KEY and not fresh:
        try:
            tabs = _find_tables()
            data = {k: _summarize(_series(tid, now.year), now.year) for k, tid in tabs.items()}
            if any(v.get("sido") for v in data.values()):
                st = {"fetched": now.strftime("%Y%m%d"), "data": data, "diag": DIAG}
                print("📈 주간변동률: " + ", ".join(f"{k} {v.get('t')}" for k, v in data.items()))
            else:
                st = dict(st or {}, diag=DIAG)
                print(f"⚠️ 주간변동률 자료 없음 — diag: {json.dumps(DIAG, ensure_ascii=False)[:400]}")
        except Exception as e:
            DIAG["err"] = str(e)[:300]
            st = dict(st or {}, diag=DIAG)
            print(f"⚠️ 주간변동률 받기 실패: {str(e)[:200]}")
        os.makedirs(store, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, separators=(",", ":"))
    elif not KEY:
        print("📈 REB_API_KEY 없음 — 주간변동률은 저장본 또는 준비 중")
    data = (st or {}).get("data") or {}
    with open(os.path.join(site, "weekly.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    return bool(data)
