"""구별 아파트 세대수 수집 (국토교통부 공동주택 단지 목록 · 기본 정보 API, K-apt 기반).

- 구(시군구 코드)별 단지 목록 → 단지 코드별 기본 정보(세대수)를 받아 구별로 합산합니다.
- 결과는 data/households.json 에 저장하고, 30일이 지나면 다시 받습니다.
- K-apt 는 의무관리대상 공동주택(대략 150세대 이상 등)만 포함하므로 소규모 단지는 빠집니다.

    python households.py           # 30일 지났을 때만 갱신
    python households.py --force   # 즉시 갱신
"""
import argparse
import json
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

KEY = os.environ.get("KAPT_API_KEY") or os.environ.get("MOLIT_API_KEY", "")
PATH = "data/households.json"
SIDO = "부산광역시"
REFRESH_DAYS = 30
KST = timezone(timedelta(hours=9))
API = "https://apis.data.go.kr/1613000"
# 서비스 버전이 바뀌는 경우가 있어 여러 주소를 차례로 시도
_V = [("1613000", "AptListService5", "getSigunguAptList5"), ("1613000", "AptListService4", "getSigunguAptList4"), ("1613000", "AptListService4", "getSigunguAptList"),
      ("1613000", "AptListService3", "getSigunguAptList3"), ("1613000", "AptListService2", "getSigunguAptList2"),
      ("1613000", "AptListService1", "getSigunguAptList1"), ("1613000", "AptListService", "getSigunguAptList"),
      ("1611000", "AptListService2", "getSigunguAptList"), ("1611000", "AptListService", "getSigunguAptList")]
LIST_URLS = [f"https://apis.data.go.kr/{a}/{b}/{c}" for a, b, c in _V]
_I = [("1613000", "AptListService5", "getAphusBassInfo5"), ("1613000", "AptListService5", "getAphusBassInfoV5"),
      ("1613000", "AptListService5", "getAphusBassInfo"), ("1613000", "AptBasisInfoServiceV5", "getAphusBassInfoV5"),
      ("1613000", "AptBasisInfoService5", "getAphusBassInfo5"), ("1613000", "AptBasisInfoServiceV4", "getAphusBassInfoV4"), ("1613000", "AptBasisInfoService4", "getAphusBassInfo4"),
      ("1613000", "AptBasisInfoServiceV4", "getAphusBassInfo"), ("1613000", "AptBasisInfoServiceV3", "getAphusBassInfoV3"),
      ("1613000", "AptBasisInfoServiceV2", "getAphusBassInfoV2"), ("1613000", "AptBasisInfoService1", "getAphusBassInfo1"),
      ("1613000", "AptBasisInfoService", "getAphusBassInfo"), ("1611000", "AptBasisInfoService", "getAphusBassInfo")]
INFO_URLS = [f"https://apis.data.go.kr/{a}/{b}/{c}" for a, b, c in _I]


def _call(urls, params):
    """urls 를 차례로 시도해 (성공한 url, item 목록, totalCount) 반환. 실패하면 마지막 오류 메시지."""
    errs = []
    for url in urls:
        last = ""
        for attempt in range(3):
            try:
                r = requests.get(url, params={"serviceKey": requests.utils.unquote(KEY), **params}, timeout=30)
            except requests.RequestException as e:
                last = f"{url} {type(e).__name__}"
                time.sleep(2 ** attempt)
                continue
            if r.status_code != 200:
                last = f"{url} HTTP {r.status_code} {' '.join(r.text.split())[:300]}"
                break
            text = r.text.strip()
            try:
                if text.startswith("{"):
                    j = r.json()
                    body = j.get("response", j).get("body", {})
                    code = str(j.get("response", j).get("header", {}).get("resultCode", "00"))
                    items = body.get("items", body.get("item", []))
                    if isinstance(items, dict) and "item" in items:
                        items = items["item"]
                    if isinstance(items, dict):
                        items = [items]
                    if code not in ("00", "000"):
                        last = f"{url} 결과코드 {code}"
                        break
                    return url, items, int(body.get("totalCount") or len(items))
                root = ET.fromstring(r.content)
                code = root.findtext(".//resultCode", "00")
                if code not in ("00", "000"):
                    last = f"{url} 결과코드 {code} {root.findtext('.//resultMsg', '')}{root.findtext('.//returnAuthMsg', '')}"
                    break
                items = [{c.tag: (c.text or "").strip() for c in it} for it in root.findall(".//item")]
                return url, items, int(root.findtext(".//totalCount", "0") or len(items))
            except (ValueError, ET.ParseError):
                last = f"{url} 응답 해석 실패 {text[:120]}"
                break
        errs.append(" ".join(last.split())[:220])
    raise RuntimeError(" | ".join(errs))


MAX_CALLS = 700        # 한 번 실행에 쓰는 최대 호출 수 (개발계정 하루 호출 한도 고려, 나머지는 다음 날 이어서)
CNT_KEYS = ("kaptdaCnt", "hoCnt", "kaptHoCnt", "hhldCnt")


def _age(d, today):
    return (today.date() - datetime.strptime(d, "%Y%m%d").date()).days if d else 9999


def _load():
    if os.path.exists(PATH):
        try:
            with open(PATH, encoding="utf-8") as f:
                st = json.load(f)
            if st.get("version") == 2:
                return st
        except Exception:
            pass
    return {"version": 2, "lists": {}, "info": {}, "gu": {}}


def _save(st):
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, separators=(",", ":"))


def update(st, lawd_codes, today):
    """단지 목록·기본정보를 조금씩 채움. 한 번에 MAX_CALLS 까지만 호출하고, 다 못 받으면 다음 실행에서 이어 받음."""
    today_s = today.strftime("%Y%m%d")
    list_urls, info_urls = list(LIST_URLS), list(INFO_URLS)
    calls, logged = 0, False
    for gu, code in lawd_codes.items():
        lst = st["lists"].get(gu)
        if not lst or _age(lst["date"], today) >= REFRESH_DAYS:
            if calls >= MAX_CALLS:
                return calls
            codes, page = [], 1
            while True:
                url, items, total = _call(list_urls, {"sigunguCode": code, "pageNo": page, "numOfRows": 1000})
                list_urls = [url]
                calls += 1
                codes += [c["kaptCode"] for c in items if c.get("kaptCode")]
                if not items or page * 1000 >= total:
                    break
                page += 1
            if not codes:
                print(f"⚠️ {gu} 단지 목록이 비어 있음 (호출 한도 초과 가능) — 다음 실행에서 다시 시도")
                return calls
            st["lists"][gu] = {"date": today_s, "codes": codes}
            print(f"📋 {gu} 단지 목록 {len(codes)}개")
        for kcode in st["lists"][gu]["codes"]:
            inf = st["info"].get(kcode)
            if inf and _age(inf["date"], today) < REFRESH_DAYS:
                continue
            if calls >= MAX_CALLS:
                return calls
            url, items, _ = _call(info_urls, {"kaptCode": kcode})
            info_urls = [url]
            calls += 1
            if not items:
                print(f"⚠️ 기본정보 응답이 비어 있음 ({kcode}) — 호출 한도 초과 가능, 다음 실행에서 이어 받음")
                return calls
            it = items[0]
            if not logged:
                print(f"ℹ️ 기본정보 항목 필드: {it}")
                logged = True
            cnt = 0
            for k in CNT_KEYS:
                v = str(it.get(k) or "").replace(",", "")
                if v.isdigit() and int(v) > 0:
                    cnt = int(v)
                    break
            st["info"][kcode] = {"gu": gu, "kind": it.get("codeAptNm", ""), "cnt": cnt, "date": today_s}
            time.sleep(0.05)
    return calls


def aggregate(st, lawd_codes):
    """목록의 모든 단지 정보가 모인 구만 합산."""
    out = {}
    for gu in lawd_codes:
        lst = st["lists"].get(gu)
        if not lst:
            continue
        infos = [st["info"].get(c) for c in lst["codes"]]
        if any(i is None for i in infos):
            continue
        apts = [i for i in infos if not i["kind"] or "아파트" in i["kind"] or "주상복합" in i["kind"]]
        out[gu] = {"households": sum(i["cnt"] for i in apts), "complexes": sum(1 for i in apts if i["cnt"])}
    return out


def ensure(lawd_codes, today=None, force=False):
    """세대수를 이어 받고, 완성된 {구: 세대수} 를 돌려줌. 실패해도 지금까지 받은 값은 보존."""
    today = today or datetime.now(KST)
    # 1순위: K-apt 단지 기본정보 파일 (data/kapt/kapt_complexes.csv) — API 호출 없이 바로 사용
    import kapt
    from_file = kapt.households_by_sigungu(SIDO)
    if from_file and all(from_file.get(g) for g in lawd_codes):
        print(f"🏢 세대수: K-apt 파일 사용 ({SIDO} {len(from_file)}개 구·군, {sum(from_file.values()):,}세대)")
        return {g: from_file[g] for g in lawd_codes}
    st = _load()
    if force:
        st = {"version": 2, "lists": {}, "info": {}, "gu": {}}
    if KEY:
        try:
            calls = update(st, lawd_codes, today)
            print(f"🏢 세대수 수집: 이번 호출 {calls}회 · 단지 정보 {len(st['info'])}개 보유")
        except Exception as e:
            print(f"⚠️ 세대수 수집 중단 — 받은 데까지 저장: {str(e)[:300]}")
        st["gu"] = aggregate(st, lawd_codes)
        st["source"] = "국토교통부 공동주택 기본정보(K-apt)"
        _save(st)
        done = len(st["gu"])
        print(f"🏢 세대수 완성 구 {done}/{len(lawd_codes)}: " + ", ".join(f"{g} {v['households']:,}" for g, v in st["gu"].items()))
    return {gu: v["households"] for gu, v in st.get("gu", {}).items() if v.get("households")}


if __name__ == "__main__":
    from Dashboard import BUSAN_LAWD_CD
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    print(ensure(BUSAN_LAWD_CD, force=ap.parse_args().force))
