"""배정 초등학교 (통학구역) — 학구도안내서비스(한국교육시설안전원) '초등학교 통학구역 및 공동통학구역' SHP.

- 반기(3·9월)마다 갱신되는 전국 파일(약 35MB zip)을 받아 시도별 구역만 store/schoolzone_{시도}.json 에 저장 (90일 유지)
- 단지 좌표(WGS84)를 EPSG:5186 으로 바꿔 어느 통학구역 안에 있는지 판단 → 학교 이름 ('남천초통학구역' → '남천초')
- 공동통학구역(한 구역에 학교 여럿)은 학교가 둘 이상 나옴
"""
import io
import json
import os
import re
import zipfile
from datetime import datetime

import requests

B = "https://schoolzone.emac.kr"
KEEP_DAYS = 90
UA = {"User-Agent": "Mozilla/5.0 (compatible; nextdoorprice-bot)"}


def _download():
    """공공데이터 목록에서 가장 최근 '초등학교 통학구역' zip 을 받는다."""
    s = requests.Session()
    s.headers.update(UA)
    html = s.get(B + "/publicData/publicDataList.do", timeout=30).text
    ids = re.findall(r"fn_view_detail\(event,\s*'(\d+)'\)", html)
    print(f"🏫 학구도 목록 {len(ids)}건")
    for ntt in ids[:16]:
        t = s.post(B + "/publicData/publicDataView.do", data={"nttId": ntt, "pageIndex": 1}, timeout=30).text
        files = re.findall(r"([^<>\"']{3,80}\.zip)", t)
        if not any("초등학교통학구역" in f.replace(" ", "") for f in files):   # 첨부 파일 이름으로 판단 (표준안 문서 제외)
            continue
        m = re.search(r'data-nttId="(\d+)"\s+data-atchFileId="([^"]+)"\s+data-fileSn="(\d+)"', t, re.I) or \
            re.search(r"fn_file_download\(\s*'?(\d+)'?\s*,\s*'([^']+)'\s*,\s*'?(\d+)'?", t)
        if not m:
            print("🏫 첨부 정보 못 찾음", ntt)
            continue
        z = s.get(B + "/publicData/publicDataFileDownload.do",
                  params={"nttId": m.group(1), "atchFileId": m.group(2), "fileSn": m.group(3)}, timeout=300)
        print(f"🏫 통학구역 파일 {ntt}: {len(z.content):,}B")
        if z.content[:2] == b"PK":
            return z.content
    print("🏫 통학구역 파일을 찾지 못함")
    return None


def _extract(data, sido_code):
    import shapefile
    zf = zipfile.ZipFile(io.BytesIO(data))
    shp = next(n for n in zf.namelist() if n.lower().endswith(".shp"))
    base = shp[:-4]
    r = shapefile.Reader(shp=io.BytesIO(zf.read(shp)), dbf=io.BytesIO(zf.read(base + ".dbf")), encoding="cp949")
    names = [f[0] for f in r.fields[1:]]
    out = []
    for sr in r.iterShapeRecords():
        rec = dict(zip(names, list(sr.record)))
        if str(rec.get("SD_CD")) != sido_code:
            continue
        pts, parts = sr.shape.points, list(sr.shape.parts) + [len(sr.shape.points)]
        rings = [[[round(x), round(y)] for x, y in pts[parts[i]:parts[i + 1]]] for i in range(len(parts) - 1)]
        out.append({"n": rec.get("HAKGUDO_NM", ""), "gb": str(rec.get("HAKGUDO_GB", "")),
                    "bb": [round(v) for v in sr.shape.bbox], "r": rings})
    return out


def load(store, sido_code, today):
    """시도 통학구역 목록 (저장본이 오래됐으면 새로 받음, 실패하면 저장본)."""
    p = os.path.join(store, f"schoolzone_{sido_code}.json")
    st = None
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            st = json.load(f)
    fresh = st and (today - datetime.strptime(st["date"], "%Y%m%d")).days < KEEP_DAYS
    if not fresh:
        try:
            data = _download()
            if data:
                zones = _extract(data, sido_code)
                print(f"🏫 통학구역 {sido_code}: 시도 구역 {len(zones)}곳")
                if zones:
                    st = {"date": today.strftime("%Y%m%d"), "zones": zones}
                    with open(p, "w", encoding="utf-8") as f:
                        json.dump(st, f, ensure_ascii=False, separators=(",", ":"))
                    print(f"🏫 통학구역 {sido_code}: {len(zones)}곳 받음")
        except Exception as e:
            print(f"⚠️ 통학구역 받기 실패 — {'저장본' if st else '배정학교 없이'} 진행: {str(e)[:150]}")
    return (st or {}).get("zones", [])


def _inside(x, y, ring):
    c = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
            c = not c
        j = i
    return c


_TF = None


def to5186(lng, lat):
    global _TF
    if _TF is None:
        from pyproj import Transformer
        _TF = Transformer.from_crs(4326, 5186, always_xy=True)
    return _TF.transform(lng, lat)


def schools_at(zones, lng, lat):
    """좌표가 속한 통학구역의 학교 이름들 (예: ['남천초'])."""
    x, y = to5186(float(lng), float(lat))
    out = []
    for z in zones:
        b = z["bb"]
        if not (b[0] <= x <= b[2] and b[1] <= y <= b[3]):
            continue
        n = sum(1 for ring in z["r"] if _inside(x, y, ring))   # 구멍(내부 고리)까지 고려: 홀수면 안쪽
        if n % 2 == 1:
            base = re.sub(r"\(.*?\)|통학구역|공동|[\s,·/]", "", z["n"])   # '금정초공덕초금성초공동(일방)' → 학교 3곳
            for nm in re.findall(r".+?초(?:등학교)?(?=$|[^등])", base) or [base]:
                nm = nm.replace("초등학교", "초")
                if nm and nm not in out:
                    out.append(nm)
    return out
