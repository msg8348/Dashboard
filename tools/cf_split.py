"""Cloudflare Pages 배포 준비: 사이트(site/)를 둘로 나눔.

    python tools/cf_split.py site cfsite r2pages

- cfsite/ : 단지·분양권 페이지(/{시도}/apt/*, /{시도}/pre/*)를 뺀 나머지 → Cloudflare Pages (파일 2만 개 한도)
- r2pages/pages/{시도}/apt|pre/*.html : 단지·분양권 페이지 → R2 (Pages Function 이 꺼내서 보여줌)
  날짜만 바뀌는 부분(?v=날짜, const TODAY, 'YY.MM.DD 기준')은 자리표시로 바꿔 저장 → 내용이 같으면 다시 올리지 않음.
  Function 이 cfsite/today.txt 의 날짜로 채워 보여줌.
- cfsite/_routes.json : 단지·분양권 주소만 Function 으로 (나머지는 정적 파일 그대로)
"""
import json
import os
import re
import shutil
import sys

src, out, r2 = sys.argv[1], sys.argv[2], sys.argv[3]
for d in (out, r2):
    shutil.rmtree(d, ignore_errors=True)

sidos = sorted(d for d in os.listdir(src) if os.path.isdir(os.path.join(src, d, "apt")) or os.path.isdir(os.path.join(src, d, "pre")))
skip = {os.path.join(src, s, k) for s in sidos for k in ("apt", "pre")}
shutil.copytree(src, out, ignore=lambda d, names: [n for n in names if os.path.join(d, n) in skip])

today = ""
n = 0
for s in sidos:
    for k in ("apt", "pre"):
        d = os.path.join(src, s, k)
        if not os.path.isdir(d):
            continue
        dst = os.path.join(r2, "pages", s, k)
        os.makedirs(dst, exist_ok=True)
        for fn in os.listdir(d):
            with open(os.path.join(d, fn), encoding="utf-8") as f:
                html = f.read()
            m = re.search(r"const TODAY = '(\d{8})'", html)
            if m:
                t = m.group(1)
                today = max(today, t)
                html = (html.replace(f"?v={t}", "?v=__TODAY__").replace(f"const TODAY = '{t}'", "const TODAY = '__TODAY__'")
                        .replace(f">{t[2:4]}.{t[4:6]}.{t[6:8]} 기준<", ">__TODAY_DOT__ 기준<"))
            with open(os.path.join(dst, fn), "w", encoding="utf-8") as f:
                f.write(html)
            n += 1

with open(os.path.join(out, "today.txt"), "w") as f:
    f.write(today)
with open(os.path.join(out, "_routes.json"), "w") as f:   # Function 은 단지·분양권 주소에서만 (시도별 규칙, 100개 한도 안)
    json.dump({"version": 1, "include": [f"/{s}/{k}/*" for s in sidos for k in ("apt", "pre")], "exclude": []}, f)
cnt = sum(len(fs) for _, _, fs in os.walk(out))
print(f"☁️ Cloudflare Pages: 정적 파일 {cnt:,}개 · R2 단지·분양권 페이지 {n:,}개 · 기준일 {today}")
if cnt > 19000:
    sys.exit("정적 파일이 2만 개 한도에 가까움 — 나누는 방식 점검 필요")
