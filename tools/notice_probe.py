"""청약홈 입주자모집공고문(PDF) 분양가 표 읽기 시험.

    python tools/notice_probe.py 2025000415      # 베뉴브 해운대

1) 청약홈 API 상세·주택형 응답의 모든 항목 출력 (공고문 주소, 최고 분양가 필드 확인)
2) 공고 페이지에서 PDF 링크 찾기 → 내려받기
3) PDF 에서 '공급금액/분양가' 가 나오는 쪽의 글자·표를 출력
"""
import io
import json
import os
import re
import sys

import requests

KEY = requests.utils.unquote(os.environ.get("MOLIT_API_KEY", ""))
BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"
HID = sys.argv[1] if len(sys.argv) > 1 else "2025000415"
UA = {"User-Agent": "Mozilla/5.0 (compatible; nextdoorprice-bot)"}


def api(op):
    r = requests.get(f"{BASE}/{op}", params={"page": 1, "perPage": 100, "serviceKey": KEY, "returnType": "JSON",
                                             "cond[HOUSE_MANAGE_NO::EQ]": HID}, timeout=60)
    print(f"\n### {op} HTTP {r.status_code}")
    rows = r.json().get("data") or []
    for x in rows[:12]:
        print(json.dumps(x, ensure_ascii=False))
    return rows


det = api("getAPTLttotPblancDetail")
api("getAPTLttotPblancMdl")
if not det:
    sys.exit("상세 없음")
d = det[0]
urls = [v for v in d.values() if isinstance(v, str) and v.startswith("http")]
print("\n### 상세의 주소들:", urls)

pdfs = []
s = requests.Session()
s.headers.update(UA)
for u in urls:
    try:
        r = s.get(u, timeout=60)
    except requests.RequestException as e:
        print("접속 실패", u, e)
        continue
    print(f"\n### GET {u} → {r.status_code} {r.headers.get('content-type')} {len(r.content):,}B")
    if r.content[:4] == b"%PDF":
        pdfs.append((u, r.content))
        continue
    html = r.text
    links = set(re.findall(r'''(?:href|src)=["']([^"']+)["']''', html))
    links |= set(re.findall(r"(https?://[^\s\"'<>]+\.pdf[^\s\"'<>]*)", html, re.I))
    cand = [l for l in links if re.search(r"pdf|atch|file|down", l, re.I)]
    print("PDF 후보:", cand[:30])
    for m in re.findall(r"""(fn\w*Down\w*\([^)]*\)|fileDown\w*\([^)]*\)|downLoad\w*\([^)]*\))""", html)[:10]:
        print("다운로드 함수:", m)
    for l in cand[:10]:
        full = requests.compat.urljoin(u, l.replace("&amp;", "&"))
        try:
            rr = s.get(full, timeout=90)
        except requests.RequestException as e:
            print("  실패", full, e)
            continue
        print(f"  {full} → {rr.status_code} {rr.headers.get('content-type')} {len(rr.content):,}B")
        if rr.content[:4] == b"%PDF":
            pdfs.append((full, rr.content))

if not pdfs:
    sys.exit("PDF 를 찾지 못함")
import pdfplumber

for u, data in pdfs[:2]:
    print(f"\n======== PDF {u} ({len(data):,}B)")
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        print("쪽수", len(pdf.pages))
        shown = 0
        for i, pg in enumerate(pdf.pages):
            t = pg.extract_text() or ""
            if not re.search(r"공급금액|분양가|분양금액", t):
                continue
            print(f"\n--- {i + 1}쪽 글자 (앞 2500자)\n{t[:2500]}")
            for tb in pg.extract_tables()[:3]:
                print(f"\n--- {i + 1}쪽 표 {len(tb)}행")
                for row in tb[:40]:
                    print(" | ".join((c or "").replace("\n", " ") for c in row))
            shown += 1
            if shown >= 3:
                break
        if not shown:
            print("분양가 글자를 찾지 못함 (이미지 PDF 가능성) · 첫 쪽 글자:", (pdf.pages[0].extract_text() or "")[:500])
