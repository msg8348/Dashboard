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
REFRESH_DAYS = 30
KST = timezone(timedelta(hours=9))
API = "https://apis.data.go.kr/1613000"
# 서비스 버전이 바뀌는 경우가 있어 여러 주소를 차례로 시도
LIST_URLS = [f"{API}/AptListService3/getSigunguAptList3", f"{API}/AptListService2/getSigunguAptList2"]
INFO_URLS = [f"{API}/AptBasisInfoServiceV4/getAphusBassInfoV4", f"{API}/AptBasisInfoServiceV3/getAphusBassInfoV3",
             f"{API}/AptBasisInfoService1/getAphusBassInfo"]


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
        errs.append(" ".join(last.split()))
    raise RuntimeError(" | ".join(errs))


def collect(lawd_codes):
    list_urls, info_urls = list(LIST_URLS), list(INFO_URLS)
    out, calls, fails = {}, 0, 0
    for gu, code in lawd_codes.items():
        complexes, page = [], 1
        while True:
            url, items, total = _call(list_urls, {"sigunguCode": code, "pageNo": page, "numOfRows": 1000})
            list_urls = [url]   # 처음 성공한 주소만 계속 사용
            calls += 1
            complexes += items
            if not items or page * 1000 >= total:
                break
            page += 1
        hh, n, kinds = 0, 0, {}
        for c in complexes:
            kcode = c.get("kaptCode")
            if not kcode:
                continue
            try:
                url, items, _ = _call(info_urls, {"kaptCode": kcode})
                info_urls = [url]
            except RuntimeError as e:
                fails += 1
                if fails <= 3:
                    print(f"⚠️ 기본정보 실패 {kcode}: {e}")
                if fails >= 30 and n == 0:
                    raise
                continue
            calls += 1
            it = items[0] if items else {}
            kind = it.get("codeAptNm", "")
            kinds[kind] = kinds.get(kind, 0) + 1
            if kind and "아파트" not in kind and "주상복합" not in kind:
                continue   # 연립·다세대 등 제외
            cnt = it.get("kaptdaCnt") or it.get("hoCnt") or 0
            try:
                cnt = int(str(cnt).replace(",", ""))
            except ValueError:
                cnt = 0
            if cnt:
                hh += cnt
                n += 1
            time.sleep(0.05)
        out[gu] = {"households": hh, "complexes": n}
        print(f"🏢 {gu}: 단지 {n}개 · {hh:,}세대 (목록 {len(complexes)}개, 분류 {kinds})")
    print(f"✅ 세대수 수집 완료 (요청 {calls}회, 실패 {fails}회)")
    return out


def ensure(lawd_codes, today=None, force=False):
    """필요하면 세대수를 새로 받고, 저장된 {구: 세대수} 를 돌려줌. 실패해도 기존 값 유지."""
    today = today or datetime.now(KST)
    old = {}
    if os.path.exists(PATH):
        with open(PATH, encoding="utf-8") as f:
            old = json.load(f)
    fresh = old.get("date") and (today.date() - datetime.strptime(old["date"], "%Y%m%d").date()).days < REFRESH_DAYS
    if KEY and (force or not fresh):
        try:
            data = collect(lawd_codes)
            if sum(v["households"] for v in data.values()) > 0:
                old = {"date": today.strftime("%Y%m%d"), "source": "국토교통부 공동주택 기본정보(K-apt)", "gu": data}
                os.makedirs(os.path.dirname(PATH), exist_ok=True)
                with open(PATH, "w", encoding="utf-8") as f:
                    json.dump(old, f, ensure_ascii=False, indent=1)
        except Exception as e:
            print(f"⚠️ 세대수 수집 실패 — 기존 값 사용: {e}")
    return {gu: v["households"] for gu, v in old.get("gu", {}).items() if v.get("households")}


if __name__ == "__main__":
    from Dashboard import BUSAN_LAWD_CD
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    print(ensure(BUSAN_LAWD_CD, force=ap.parse_args().force))
