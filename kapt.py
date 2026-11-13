"""전국 공동주택 단지 기본정보 (K-apt) 조회.

data/kapt/kapt_complexes.csv : K-apt 단지 기본정보 엑셀(전국 약 2.2만 단지)에서 필요한 항목만 뽑은 파일.
  sido, sigungu, eupmyeon, dongri, kapt_code, name, kind(단지분류), jibun_addr, road_addr, sale_type,
  approval_date(사용승인일), buildings(동수), households(세대수), sale_households, rent_households,
  heating, corridor, builder(시공사), max_floor, basement_floors, parking, elevators

- 시도 이름은 K-apt 표기 그대로 (예: 부산광역시, 경기도, 전남광주통합특별시)
- 시군구는 구가 있는 시의 경우 붙여 씀 (예: 용인기흥구, 성남분당구)
- K-apt 는 의무관리대상 공동주택 위주라 소규모 단지는 빠질 수 있음
- 파일 갱신: K-apt 에서 새 엑셀을 받아 tools 없이 아래 refresh_from_xlsx() 로 다시 만들면 됨
"""
import csv
import os
import re
from functools import lru_cache

PATH = "data/kapt/kapt_complexes.csv"
APT_KINDS = ("아파트", "주상복합")   # '도시형 생활주택(아파트)' 등도 포함, 연립·다세대 제외


def _norm(s):
    return re.sub(r"[^0-9A-Za-z가-힣]", "", s or "").lower()


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


@lru_cache(maxsize=1)
def load():
    if not os.path.exists(PATH):
        return []
    with open(PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["households"] = _int(r["households"])
    return rows


def is_apartment(r):
    return any(k in (r.get("kind") or "") for k in APT_KINDS)


def households_by_sigungu(sido):
    """{시군구: 아파트·주상복합 세대수 합계}"""
    out = {}
    for r in load():
        if r["sido"] == sido and is_apartment(r):
            out[r["sigungu"]] = out.get(r["sigungu"], 0) + r["households"]
    return out


def find(name, sido=None, sigungu=None):
    """단지명으로 찾기 (공백·괄호 무시, 포함 검색)."""
    key = _norm(name)
    return [r for r in load() if (not sido or r["sido"] == sido) and (not sigungu or r["sigungu"] == sigungu)
            and key in _norm(r["name"])]


def refresh_from_xlsx(xlsx_path):
    """K-apt 단지 기본정보 엑셀(첫 줄 안내문, 둘째 줄 헤더)로 CSV 를 다시 만든다."""
    import openpyxl
    cols = [("시도", "sido"), ("시군구", "sigungu"), ("읍면", "eupmyeon"), ("동리", "dongri"), ("단지코드", "kapt_code"),
            ("단지명", "name"), ("단지분류", "kind"), ("법정동주소", "jibun_addr"), ("도로명주소", "road_addr"),
            ("분양형태", "sale_type"), ("사용승인일", "approval_date"), ("동수", "buildings"), ("세대수", "households"),
            ("분양세대수", "sale_households"), ("임대세대수", "rent_households"), ("난방방식", "heating"),
            ("복도유형", "corridor"), ("시공사", "builder"), ("최고층수", "max_floor"), ("지하층수", "basement_floors"),
            ("총주차대수", "parking"), ("승강기(승객용)", "elevators")]
    ws = openpyxl.load_workbook(xlsx_path).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    head = {h: i for i, h in enumerate(rows[1])}

    def clean(v):
        s = "" if v is None else str(v).strip()
        return s[:-2] if s.endswith(".0") and s[:-2].isdigit() else s

    data = sorted(rows[2:], key=lambda r: (r[head["시도"]] or "", r[head["시군구"]] or "", r[head["단지명"]] or ""))
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([c[1] for c in cols])
        for r in data:
            w.writerow([clean(r[head[c[0]]]) for c in cols])
    load.cache_clear()
    return len(data)
