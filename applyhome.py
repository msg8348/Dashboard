"""청약홈 분양정보 (한국부동산원) — 분양권 카드용 입주예정월·공급세대수·주택형별 공급세대수.

공공데이터포털 '한국부동산원_청약홈 분양정보 조회 서비스' (odcloud)
    APT 분양정보 상세  : /getAPTLttotPblancDetail  (HOUSE_MANAGE_NO, HOUSE_NM, HSSPLY_ADRES, TOT_SUPLY_HSHLDCO, MVN_PREARNGE_YM …)
    APT 주택형별 상세  : /getAPTLttotPblancMdl     (HOUSE_MANAGE_NO, HOUSE_TY '084.9779A', SUPLY_HSHLDCO, SPSPLY_HSHLDCO …)

load(path, key) → [{id, name, addr, total, mvn, url(공고 페이지), builder, pbl(모집공고일),
                     types: [[전용면적, 세대수, 약식표기, 최고 분양가(만원), 전용면적(정밀)], ...]}]  (7일마다 다시 받음, 실패하면 저장본)
"""
import json
import os
import re
import time
from datetime import datetime

import requests

BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"
REFRESH_DAYS = 1   # 청약 일정(청약단지 메뉴) 때문에 매일


def _pages(op, key, per=1000, max_pages=200):
    page, out = 1, []
    while page <= max_pages:
        r = None
        for attempt in range(3):
            try:
                r = requests.get(f"{BASE}/{op}", params={"page": page, "perPage": per, "serviceKey": requests.utils.unquote(key),
                                                         "returnType": "JSON"}, timeout=(10, 90))
                if r.status_code == 200:
                    break
            except requests.RequestException:
                r = None
            time.sleep(3 * (attempt + 1))
        if r is None or r.status_code != 200:
            raise RuntimeError(f"청약홈 {op} {page}쪽 실패: {getattr(r, 'status_code', '-')} {(r.text[:150] if r is not None else '')}")
        j = r.json()
        rows = j.get("data") or []
        if page == 1:
            print(f"🏗️ 청약홈 {op}: 전체 {j.get('totalCount', '?')}건 · 항목 {list(rows[0].keys())[:14] if rows else '-'}")
        out += rows
        if not rows or page * per >= int(j.get("totalCount") or j.get("matchCount") or 0):
            break
        page += 1
    return out


def _num(v):
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return 0


SCH = {   # 청약홈 접수 일정 필드
    "sp1": "SPSPLY_RCEPT_BGNDE", "sp2": "SPSPLY_RCEPT_ENDDE",
    "r1a": "GNRL_RNK1_CRSPAREA_RCPTDE", "r1b": "GNRL_RNK1_ETC_AREA_RCPTDE", "r2": "GNRL_RNK2_CRSPAREA_RCPTDE",
    "rc1": "RCEPT_BGNDE", "rc2": "RCEPT_ENDDE", "win": "PRZWNER_PRESNATN_DE",
    "ct1": "CNTRCT_CNCLS_BGNDE", "ct2": "CNTRCT_CNCLS_ENDDE",
}


def _d(v):
    """'2026-11-18' → '20261118'"""
    v = re.sub(r"\D", "", str(v or ""))[:8]
    return v if len(v) == 8 else ""


def fetch(key):
    det = _pages("getAPTLttotPblancDetail", key)
    mdl = _pages("getAPTLttotPblancMdl", key)
    types = {}
    for m in mdl:
        hid = str(m.get("HOUSE_MANAGE_NO") or "")
        ty = str(m.get("HOUSE_TY") or "")
        mt = re.match(r"\s*0*(\d+(?:\.\d+)?)", ty)
        if not hid or not mt:
            continue
        n = _num(m.get("SUPLY_HSHLDCO")) + _num(m.get("SPSPLY_HSHLDCO"))   # 일반공급 + 특별공급
        letter = re.sub(r"[^A-Za-z]", "", ty[mt.end():])
        # [전용면적, 세대수, 약식표기(84A · 글자가 없으면 99), 최고 분양가(만원), 전용면적(소수 넷째 자리)]
        types.setdefault(hid, []).append([round(float(mt.group(1)), 2), n, f"{int(float(mt.group(1)))}{letter.upper()}",
                                          _num(m.get("LTTOT_TOP_AMOUNT")), float(mt.group(1)), _num(m.get("SPSPLY_HSHLDCO"))])
    out = []
    for d in det:
        hid = str(d.get("HOUSE_MANAGE_NO") or "")
        if not hid:
            continue
        out.append({"id": hid, "name": str(d.get("HOUSE_NM") or ""), "addr": str(d.get("HSSPLY_ADRES") or ""),
                    "total": _num(d.get("TOT_SUPLY_HSHLDCO")), "mvn": re.sub(r"\D", "", str(d.get("MVN_PREARNGE_YM") or ""))[:6],
                    "types": types.get(hid, []), "url": str(d.get("PBLANC_URL") or ""),
                    "builder": str(d.get("CNSTRCT_ENTRPS_NM") or "").strip(), "pbl": str(d.get("RCRIT_PBLANC_DE") or ""),
                    # 청약 일정 · 규제 (청약단지 메뉴)
                    "sch": {k: _d(d.get(f)) for k, f in SCH.items() if _d(d.get(f))},
                    "kind": str(d.get("HOUSE_DTL_SECD_NM") or ""), "hp": str(d.get("HMPG_ADRES") or ""),
                    "reg": [x for x, f in (("투기과열지구", "SPECLT_RDN_EARTH_AT"), ("조정대상지역", "MDAT_TRGET_AREA_SECD"), ("분양가상한제", "PARCPRC_ULS_AT"))
                            if str(d.get(f) or "").upper() in ("Y", "1")]})
    return out


def load(path, key, today=None):
    today = today or datetime.now()
    st = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
    fresh = st and st.get("v") == 3 and (today.date() - datetime.strptime(st["date"], "%Y%m%d").date()).days < REFRESH_DAYS
    if key and not fresh:
        try:
            rows = fetch(key)
            if rows:
                st = {"v": 3, "date": today.strftime("%Y%m%d"), "houses": rows}
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(st, f, ensure_ascii=False, separators=(",", ":"))
                print(f"🏗️ 청약홈 분양정보 {len(rows):,}개 단지 저장 (주택형 정보 {sum(1 for r in rows if r['types']):,}개)")
        except Exception as e:
            print(f"⚠️ 청약홈 분양정보 갱신 실패 — {'저장본' if st else '정보 없이'} 진행: {str(e)[:200]}")
    return (st or {}).get("houses", [])
