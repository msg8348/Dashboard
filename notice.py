"""청약홈 입주자모집공고문(PDF)에서 타입·층별 분양가와 총 세대수 읽기.

    get(house, cache, budget) → {"prices": {"84A": [[최저층, 최고층, 분양가(만원)], ...]}, "ok": bool,
                                  "total": 총세대, "gen": 일반분양, "mem": 조합원(토지등소유자), "res": 보류지}
결과는 store/notice.json 에 단지별로 저장해 한 번만 받는다 (못 읽은 단지는 30일 뒤 다시 시도).
"""
import io
import json
import os
import re
from datetime import datetime

import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; nextdoorprice-bot)"}
ROW = re.compile(r"(?<![\d,])(\d{1,2})(?:\s*[-~]\s*(\d{1,2}))?\s*층\s+(\d{1,3})\s+([\d,.]+)\s+([\d,.]+)\s+([\d,.]+|-)\s+(\d{1,3}(?:,\d{3}){2,})")
RETRY_DAYS = 30


def _int(s):
    try:
        return int(str(s).replace(",", ""))
    except ValueError:
        return 0


def pdf_links(url, s):
    r = s.get(url, timeout=60)
    r.raise_for_status()
    links = re.findall(r"""https?://static\.applyhome\.co\.kr/[^"'\s<>]*getAtchmnfl\.do[^"'\s<>]*""", r.text)
    return list(dict.fromkeys(l.replace("&amp;", "&") for l in links))


def parse(data, labels):
    """PDF → (가격표, 세대 정보). labels: 이 단지 약식표기 목록 (예: 59A, 84A, 99)."""
    import pdfplumber
    tok = re.compile(r"(?:(?<=\s)|^)(" + "|".join(sorted(map(re.escape, labels), key=len, reverse=True)) + r")(?=\s|$|,)")
    prices, info = {}, {}
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = pdf.pages[:20]
        texts = [(pg.extract_text() or "") for pg in pages]
        whole = "\n".join(texts)
        m = re.search(r"총\s*([\d,]+)\s*세대", whole)
        if m:
            info["total"] = _int(m.group(1))
        for k, pat in (("gen", r"일반\s*분양\s*([\d,]+)\s*세대"), ("mem", r"(?:토지등소유자|조합원)(?:\s*분양)?\s*([\d,]+)\s*세대"),
                       ("res", r"보류지\s*([\d,]+)\s*세대")):
            m = re.search(pat, whole)
            if m:
                info[k] = _int(m.group(1))
        start = next((i for i, t in enumerate(texts) if re.search(r"공급금액|분양금액|분양가격", t) and ROW.search(t)), None)
        if start is None:
            return prices, info
        cur = None
        for pg in pages[start:start + 6]:
            cells = [c for tb in pg.extract_tables() for row in tb for c in row if c and ROW.search(c)]
            if not cells:   # 표로 안 잡히면 줄 단위
                cells = (pg.extract_text() or "").split("\n")
            for c in cells:
                c = c.replace("\n", " ")
                found = tok.findall(c)
                if found:
                    cur = found[0]
                for m in ROW.finditer(c):
                    if not cur:
                        continue
                    lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
                    won = _int(m.group(7))
                    if won > 10 ** 7:
                        prices.setdefault(cur, []).append([lo, hi, round(won / 10000)])
    return prices, info


def check(prices, types):
    """타입별 최고가가 청약홈 최고 분양가와 맞는 비율로 읽기가 맞았는지 판단."""
    tops = {t[2]: t[3] for t in types if len(t) > 3 and t[3]}
    hit = sum(1 for l, rows in prices.items() if l in tops and abs(max(r[2] for r in rows) - tops[l]) <= 10)
    return bool(tops) and hit >= max(1, len(tops) * 0.6)


def get(house, cache, today, budget):
    """캐시에 있으면 그대로, 없으면 (budget 남을 때) 받아서 읽는다. budget: [남은 횟수]."""
    hid = house["id"]
    c = cache.get(hid)
    if c and (c.get("ok") or (today - datetime.strptime(c["date"], "%Y%m%d")).days < RETRY_DAYS):
        return c
    if budget[0] <= 0 or not house.get("url") or not house.get("types") or len(house["types"][0]) < 4:
        return c
    budget[0] -= 1
    labels = [t[2] for t in house["types"]]
    out = {"date": today.strftime("%Y%m%d"), "ok": False, "prices": {}}
    s = requests.Session()
    s.headers.update(UA)
    try:
        for link in pdf_links(house["url"], s)[:3]:
            r = s.get(link, timeout=120)
            if r.content[:4] != b"%PDF":
                continue
            prices, info = parse(r.content, labels)
            out.update(info)
            if prices:
                out["prices"] = prices
                out["ok"] = check(prices, house["types"])
                if out["ok"]:
                    break
    except Exception as e:
        out["err"] = str(e)[:120]
    cache[hid] = out
    print(f"📄 공고문 {house['name']}: {'분양가 읽음' if out['ok'] else '분양가 못 읽음'} · 타입 {len(out['prices'])} · 총 {out.get('total', '-')}세대")
    return out


def load(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save(path, cache):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))


def price_at(prices, label, floor):
    """그 타입·층의 분양가 (동 구분 없이 같은 층 구간들의 평균)."""
    rows = [r[2] for r in prices.get(label, []) if r[0] <= floor <= r[1]]
    return round(sum(rows) / len(rows)) if rows else 0
