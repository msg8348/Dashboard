"""부산 분양권 단지 공고문 분양가 읽기 일괄 시험: 단지별 결과 요약 + 못 읽은 단지의 추출 줄 일부."""
import os
import re
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import applyhome
import notice

KEY = os.environ.get("MOLIT_API_KEY", "")
ids = set(sys.argv[1].split(",")) if len(sys.argv) > 1 and sys.argv[1] else None
houses = [h for h in applyhome.fetch(KEY) if (h["id"] in ids if ids else "부산" in h["addr"] and h["id"] >= "2022")]
print(f"대상 {len(houses)}곳")
s = requests.Session()
s.headers.update(notice.UA)
ok = 0
for h in houses:
    tops = {t[2]: t[3] for t in h["types"]}
    try:
        links = notice.pdf_links(h["url"], s)
        data = next((r.content for r in (s.get(l, timeout=120) for l in links[:3]) if r.content[:4] == b"%PDF"), None)
    except Exception as e:
        print(f"✗ {h['id']} {h['name']} 받기 실패 {e}")
        continue
    if not data:
        print(f"✗ {h['id']} {h['name']} PDF 없음")
        continue
    prices, info = notice.parse(data, h["types"])
    good = notice.check(prices, h["types"])
    ok += good
    miss = [l for l in tops if l not in prices]
    print(f"{'✓' if good else '✗'} {h['id']} {h['name']} · 타입 {len(prices)}/{len(tops)} · 총 {info.get('total')} 일반 {info.get('gen')} 조합 {info.get('mem')} · 빠짐 {miss[:6]}")
    if not good:
        import io
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            texts = [(pg.extract_text() or "") for pg in pdf.pages[:24]]
        i = next((i for i, t in enumerate(texts) if re.search(r"공급\s*금액|분양\s*금액|분양\s*가격|공급\s*가격", t)), None)
        print("   tops", tops)
        if i is None:
            print("   금액 쪽 없음 · 1쪽:", texts[0][:150].replace("\n", " / "))
            continue
        rows = []
        for t in texts[i:i + 6]:
            rows += notice._rows(t)
        print("   rows", rows[:12])
        lines = [l for t in texts[i:i + 4] for l in t.split("\n") if "층" in l and re.search(r"\d{2,3},\d{3}", l)]
        for l in lines[:6]:
            print("   |", l[:170])
print(f"\n성공 {ok}/{len(houses)}")
