"""네이버부동산 부산 아파트 매물 수집기.

- 단지 목록(동 단위)에서 단지별 세대수와 매매/전세/월세 매물 수를 모읍니다.  → 매물현황
- 매매 매물이 있는 단지의 매물 목록에서 84·59타입 매매 매물을 모읍니다.     → 사라진 매물
- 전날 저장한 상태(data/naver/state.json)와 비교해 사라진/신규/재등록 매물을 계산합니다.

사용법
    python naver.py --test        # 수영구 일부만 시험 수집 (저장 안 함, 로그만)
    python naver.py               # 부산 전체 수집 후 data/naver/state.json 갱신
"""

import argparse
import json
import os
import random
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

BASE = "https://new.land.naver.com"
BUSAN = "2600000000"
STATE_PATH = "data/naver/state.json"
KST = timezone(timedelta(hours=9))
REAL_ESTATE_TYPES = "APT:ABYG"          # 아파트 + 아파트 분양권
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def area_type(a):
    if 55 <= a < 65:
        return "59"
    if 78 <= a <= 88:
        return "84"
    return ""


def parse_price(s):
    """'11억 5,000' / '9억' / '8,500' -> 만원"""
    s = (s or "").replace(",", "").replace(" ", "")
    m = re.match(r"(?:(\d+)억)?(\d+)?", s)
    if not m or not (m.group(1) or m.group(2)):
        return 0
    return int(m.group(1) or 0) * 10000 + int(m.group(2) or 0)


class Naver:
    def __init__(self, delay=0.6):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                               "Accept-Language": "ko-KR,ko;q=0.9", "Referer": BASE + "/complexes"})
        self.delay = delay
        self.calls = 0
        self.fails = 0

    def login(self):
        r = self.s.get(BASE + "/complexes", timeout=20)
        print(f"[token] GET /complexes -> {r.status_code}, {len(r.text)} bytes")
        m = re.search(r'"token"\s*:\s*"([A-Za-z0-9._-]+)"', r.text)
        if m:
            self.s.headers["Authorization"] = "Bearer " + m.group(1)
            print("[token] 토큰 확보")
        else:
            print("[token] 토큰을 찾지 못함 (토큰 없이 시도)")

    def get(self, path, params=None):
        for attempt in range(4):
            time.sleep(self.delay + random.random() * self.delay)
            self.calls += 1
            try:
                r = self.s.get(BASE + path, params=params, timeout=20)
            except requests.RequestException as e:
                print(f"[warn] {path}: {e}")
                continue
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    print(f"[warn] {path}: JSON 아님 {r.text[:120]!r}")
                    return None
            print(f"[warn] {path} -> HTTP {r.status_code} {r.text[:120]!r}")
            if r.status_code == 401 and attempt == 0:
                self.login()
            elif r.status_code == 429:
                time.sleep(30 * (attempt + 1))
            else:
                time.sleep(3 * (attempt + 1))
        self.fails += 1
        return None

    def regions(self, cortar):
        j = self.get("/api/regions/list", {"cortarNo": cortar}) or {}
        return j.get("regionList", [])

    def complexes(self, dong):
        j = self.get("/api/regions/complexes",
                     {"cortarNo": dong, "realEstateType": REAL_ESTATE_TYPES, "order": ""}) or {}
        return j.get("complexList", [])

    def articles(self, complex_no, max_pages=30):
        out = []
        for page in range(1, max_pages + 1):
            j = self.get(f"/api/articles/complex/{complex_no}", {
                "realEstateType": REAL_ESTATE_TYPES, "tradeType": "A1", "tag": "::::::::",
                "rentPriceMin": 0, "rentPriceMax": 900000000, "priceMin": 0, "priceMax": 900000000,
                "areaMin": 0, "areaMax": 900000000, "showArticle": "false", "sameAddressGroup": "false",
                "priceType": "RETAIL", "page": page, "complexNo": complex_no, "type": "list", "order": "prc"})
            if not j:
                return out if out else None
            out.extend(j.get("articleList", []))
            if not j.get("isMoreData"):
                break
        return out


def collect(nv, test=False):
    nv.login()
    gus = nv.regions(BUSAN)
    print(f"[region] 부산 구·군 {len(gus)}개: {[g.get('cortarName') for g in gus]}")
    if not gus:
        raise SystemExit("구·군 목록을 받지 못했습니다 (차단 또는 구조 변경).")
    if test:
        gus = [g for g in gus if g.get("cortarName") == "수영구"] or gus[:1]

    complexes = []
    for g in gus:
        dongs = nv.regions(g["cortarNo"])
        if test:
            dongs = dongs[:2]
        for d in dongs:
            for c in nv.complexes(d["cortarNo"]):
                complexes.append({
                    "no": str(c.get("complexNo")), "name": c.get("complexName", ""),
                    "gu": g["cortarName"], "dong": d.get("cortarName", ""),
                    "type": c.get("realEstateTypeCode", ""),
                    "hh": int(c.get("totalHouseholdCount") or 0),
                    "deal": int(c.get("dealCount") or 0),
                    "lease": int(c.get("leaseCount") or 0),
                    "rent": int(c.get("rentCount") or 0),
                })
        print(f"[complex] {g['cortarName']}: 누적 단지 {len(complexes)}개 (요청 {nv.calls}회)")
    # 같은 단지가 여러 동에 걸쳐 나오면 한 번만
    complexes = list({c["no"]: c for c in complexes}.values())

    units, failed = {}, 0
    targets = [c for c in complexes if c["deal"] > 0]
    if test:
        targets = targets[:3]
    for i, c in enumerate(targets):
        arts = nv.articles(c["no"])
        if arts is None:
            failed += 1
            continue
        for a in arts:
            try:
                area = float(a.get("area2") or 0)
            except ValueError:
                area = 0
            t = area_type(area)
            if not t:
                continue
            floor = (a.get("floorInfo") or "").split("/")[0]
            key = f"{c['no']}|{a.get('buildingName','')}|{floor}|{area}"
            units.setdefault(key, {
                "articles": [], "cno": c["no"], "name": c["name"], "gu": c["gu"], "type": t,
                "pre": a.get("realEstateTypeCode") == "ABYG", "floor": floor,
                "price": parse_price(a.get("dealOrWarrantPrc")), "confirm": a.get("articleConfirmYmd", ""),
            })["articles"].append(str(a.get("articleNo")))
        if (i + 1) % 100 == 0:
            print(f"[article] {i + 1}/{len(targets)} 단지 (요청 {nv.calls}회, 실패 {failed})")
        if test:
            print(f"[article] {c['name']}: 매물 {len(arts)}건, 샘플 {arts[:1]}")
    return complexes, units, failed, len(targets)


def diff(prev_units, units):
    """사라진 매물 = 어제 있던 (단지·동·층·면적) 묶음이 오늘 통째로 없어진 것.
    재등록 = 묶음은 남아 있지만 어제의 매물번호가 모두 사라지고 새 번호로 바뀐 것 (사라진 매물에서 제외)."""
    gone, relisted, new = [], 0, 0
    for k, u in prev_units.items():
        if k not in units:
            gone.append(u)
        elif not set(u["articles"]) & set(units[k]["articles"]):
            relisted += 1
    new_by_gu = defaultdict(int)
    for k, u in units.items():
        if k not in prev_units:
            new += 1
            new_by_gu[u["gu"]] += 1
    return gone, relisted, new, new_by_gu


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args()

    started = time.time()
    nv = Naver(delay=0.6)
    complexes, units, failed, n_targets = collect(nv, test=args.test)
    print(f"[done] 단지 {len(complexes)}개, 84·59 매매 묶음 {len(units)}개, 매물 조회 실패 {failed}/{n_targets}, "
          f"요청 {nv.calls}회, {time.time() - started:.0f}초")
    if args.test:
        print("[test] 시험 수집 완료 — 저장하지 않습니다.")
        return
    if n_targets and failed > n_targets * 0.2:
        sys.exit(f"매물 조회 실패가 너무 많습니다 ({failed}/{n_targets}). 이전 상태를 유지합니다.")

    today = datetime.now(KST).strftime("%Y%m%d")
    prev = {}
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            prev = json.load(f)
    if prev.get("date") == today and prev.get("prev"):
        prev_units, prev_counts, prev_date = prev["prev"]["units"], prev["prev"]["counts"], prev["prev"]["date"]
    else:
        prev_units, prev_counts, prev_date = prev.get("units", {}), prev.get("counts", {}), prev.get("date", "")

    counts = {c["no"]: [c["deal"], c["lease"], c["rent"]] for c in complexes}
    gone, relisted, new, new_by_gu = diff(prev_units, units) if prev_units else ([], 0, 0, {})
    state = {
        "date": today, "prev_date": prev_date, "collected_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "complexes": complexes, "counts": counts, "units": units,
        "prev": {"date": prev_date, "units": prev_units, "counts": prev_counts},
        "gone": sorted(gone, key=lambda u: -u["price"]), "relisted": relisted, "new": new,
        "new_by_gu": new_by_gu, "first_run": not prev_units,
    }
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[save] 사라진 {len(gone)} · 재등록 {relisted} · 신규 {new} (비교 기준일 {prev_date or '없음'})")


if __name__ == "__main__":
    main()
