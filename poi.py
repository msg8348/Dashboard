"""단지 주변 정보: 좌표 · 가장 가까운 초등학교 · 지하철역(가장 가까운 출구) · 버스정류장, 도보 시간(추정).

- 카카오 로컬 API (KAKAO_API_KEY): 주소→좌표, 초등학교(SC4), 지하철역(SW8)·출구
- 국토교통부 TAGO 버스정류소정보 (MOLIT_API_KEY): 좌표 근처 정류장
- 도보 시간 = 직선거리 × 1.3 ÷ 분당 67m (올림) — 네이버 길찾기와 몇 분 차이 날 수 있음
결과는 store/poi.json 에 단지번호별로 저장 (한 번 찾으면 180일 유지).
"""
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests

KAKAO = os.environ.get("KAKAO_API_KEY", "")
MOLIT = requests.utils.unquote(os.environ.get("MOLIT_API_KEY", ""))
API = "https://dapi.kakao.com/v2/local"
TAGO = "https://apis.data.go.kr/1613000/BusSttnInfoInqireService/getCrdntPrxmtSttnList"
KEEP_DAYS = 180
MAX_STATION_M = 2000   # 이보다 멀면 지하철 '-'
MAX_BUS_M = 800
MAX_SCHOOL_M = 2000


def walk_min(m):
    return max(1, math.ceil(float(m) * 1.3 / 67))


def _k(path, **p):
    for attempt in range(3):
        try:
            r = requests.get(f"{API}/{path}", headers={"Authorization": f"KakaoAK {KAKAO}"}, params=p, timeout=15)
            if r.status_code == 200:
                return r.json().get("documents", [])
            if r.status_code in (401, 403):
                raise RuntimeError(f"카카오 {r.status_code} {r.text[:120]}")
        except requests.RequestException:
            pass
        time.sleep(1 + attempt)
    return []


def _dist(x1, y1, x2, y2):
    dx = (float(x2) - float(x1)) * 111320 * math.cos(math.radians(float(y1)))
    dy = (float(y2) - float(y1)) * 110540
    return math.hypot(dx, dy)


def bus(x, y):
    """TAGO: 좌표 근처 정류장 중 가장 가까운 곳 [이름, 거리m]."""
    try:
        r = requests.get(TAGO, params={"serviceKey": MOLIT, "gpsLati": y, "gpsLong": x, "_type": "json", "numOfRows": 30},
                         timeout=6)
        it = r.json()["response"]["body"]["items"]
        it = (it or {}).get("item") or []
        it = it if isinstance(it, list) else [it]
    except Exception:
        return False                      # 서비스 미승인·오류 → 버스 칸 숨김
    best = None
    for s in it:
        d = _dist(x, y, s.get("gpslong"), s.get("gpslati"))
        if best is None or d < best[1]:
            best = [str(s.get("nodenm") or ""), round(d)]
    return best if best and best[1] <= MAX_BUS_M else None


def find(addr, name):
    """주소(시 구 동 지번) → {x, y, sc: [학교, 분], st: [역, 분], bus: [정류장, 분]}"""
    d = _k("search/address.json", query=addr)
    if not d:
        d = _k("search/keyword.json", query=f"{addr.split()[-2] if len(addr.split()) > 2 else ''} {name}".strip())
    if not d:
        return None
    x, y = d[0]["x"], d[0]["y"]
    out = {"x": round(float(x), 6), "y": round(float(y), 6)}
    sc = [z for z in _k("search/category.json", category_group_code="SC4", x=x, y=y, radius=MAX_SCHOOL_M, sort="distance")
          if z["category_name"].endswith("초등학교")]
    if sc:
        out["sc"] = [sc[0]["place_name"].replace("초등학교", "초"), walk_min(sc[0]["distance"])]
    st = _k("search/category.json", category_group_code="SW8", x=x, y=y, radius=MAX_STATION_M, sort="distance")
    best = None
    for s in st[:2]:   # 가까운 역 두 곳의 출구 중 가장 가까운 출구
        exits = [z for z in _k("search/keyword.json", query=f"{s['place_name']} 출구", x=x, y=y, radius=MAX_STATION_M, sort="distance")
                 if z["category_name"].endswith("지하철출구")]
        d_ = int(exits[0]["distance"]) if exits else int(s["distance"])
        if best is None or d_ < best[1]:
            best = [s["place_name"].split()[0], d_]
    if best:
        out["st"] = [best[0], walk_min(best[1])]
    b = bus(x, y)
    if b is not False:
        out["bk"] = 1                     # 버스 정보 확인됨 (없으면 '-')
    if b:
        out["bus"] = [b[0], walk_min(b[1])]
    return out


def update(cache, targets, today, budget=1500, workers=6):
    """targets: {단지번호: (주소, 이름)}. 캐시에 없거나 오래된 곳만 budget 개까지 찾는다."""
    if not KAKAO:
        return 0
    t = today.strftime("%Y%m%d")
    todo = [(k, a, n) for k, (a, n) in targets.items()
            if k not in cache or (datetime.strptime(t, "%Y%m%d") - datetime.strptime(cache[k].get("d", "20000101"), "%Y%m%d")).days > KEEP_DAYS]
    todo = todo[:budget]
    done = 0

    def job(item):
        k, a, n = item
        try:
            return k, find(a, n)
        except RuntimeError as e:
            return k, e

    # 버스 정보가 빠진 단지(TAGO 승인 전에 찾은 곳): 좌표로 버스만 다시
    nob = [k for k in targets if k in cache and cache[k].get("x") and not cache[k].get("bk")][:budget]

    def bjob(k):
        return k, bus(cache[k]["x"], cache[k]["y"])

    with ThreadPoolExecutor(workers * 2) as ex:   # TAGO 응답이 느려 버스만 따로 더 많이 동시에
        nb = 0
        for k, b in ex.map(bjob, nob):
            if b is False:
                continue
            cache[k]["bk"] = 1
            if b:
                cache[k]["bus"] = [b[0], walk_min(b[1])]
            nb += 1
        if nob:
            print(f"🚌 버스정류장 {nb}/{len(nob)}곳 채움")
    with ThreadPoolExecutor(workers) as ex:
        for k, r in ex.map(job, todo):
            if isinstance(r, RuntimeError):
                print("⛔", r)
                break
            cache[k] = dict(r or {}, d=t)
            done += 1
    print(f"📍 주변 정보 {done}곳 새로 찾음 (남은 곳 {max(0, len([1 for k in targets if k not in cache]))})")
    return done


def load(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save(path, cache):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))


def school_walk(x, y, name):
    """배정 학교(예: '남천초')까지 도보 분 — 카카오에서 그 학교 위치를 찾아 직선거리로."""
    q = name + "등학교" if name.endswith("초") else name
    for z in _k("search/keyword.json", query=q, x=x, y=y, radius=20000, sort="distance"):
        if z["category_name"].endswith("초등학교") and z["place_name"].replace(" ", "").startswith(name[:-1] if name.endswith("초") else name):
            return walk_min(z["distance"])
    return None


def assign(cache, keys, zones, ver, budget=2000, workers=6):
    """통학구역(학구도)으로 배정 초등학교 채우기: cache[k]['as'] = [[학교, 도보분], ...]."""
    import schoolzone
    if not zones or not KAKAO:
        return 0
    todo = [k for k in keys if k in cache and cache[k].get("x") and cache[k].get("asv") != ver][:budget]

    def job(k):
        c = cache[k]
        names = schoolzone.schools_at(zones, c["x"], c["y"])
        return k, [[n, school_walk(c["x"], c["y"], n)] for n in names[:2]]

    with ThreadPoolExecutor(workers) as ex:
        for k, r in ex.map(job, todo):
            cache[k]["as"] = r
            cache[k]["asv"] = ver
    if todo:
        print(f"🏫 배정 초등학교 {len(todo)}곳 확인 (찾음 {sum(1 for k in todo if cache[k]['as'])})")
    return len(todo)
