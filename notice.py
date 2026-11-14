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


FLOOR = re.compile(r"(?<![\d,.])(\d{1,2})\s*층?\s*(?:[-~∼]\s*(\d{1,2}|최상)\s*층|층\s*(이상)|층)")
NUM = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+|-)(?![\d.])")


def _rows(text):
    """글자에서 [최저층, 최고층, 합계(원 단위 그대로)] 를 차례로 뽑는다.
    합계 = 앞의 2~3개 금액(대지비 + 건축비 (+ 부가세)) 의 합과 같은 숫자 — 열 순서가 달라도 찾을 수 있게."""
    out = []
    marks = list(FLOOR.finditer(text))
    for i, m in enumerate(marks):
        seg = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else m.end() + 400]
        nums = [0 if x == "-" else int(x.replace(",", "")) for x in NUM.findall(seg)[:14]]
        lo = int(m.group(1))
        hi = 99 if (m.group(2) == "최상" or m.group(3)) else int(m.group(2) or m.group(1))
        tot = 0
        for k in range(len(nums) - 2):
            a, b, c = nums[k], nums[k + 1], nums[k + 2]
            if a > 0 and b > 0 and abs(a + b - c) <= 2 and c >= 1000:
                tot = c
                break
            if k + 3 < len(nums):
                d = nums[k + 3]
                if a > 0 and b > 0 and abs(a + b + c - d) <= 2 and d >= 1000 and d > a:
                    tot = d
                    break
        if tot:
            out.append([lo, hi, tot])
    return out


def _segments(rows):
    """층이 다시 낮아지거나 금액이 20% 넘게 바뀌면 새 묶음 (타입이 바뀌는 곳)."""
    segs, cur = [], []
    for r in rows:
        if cur and (r[0] < cur[-1][0] or abs(r[2] - cur[-1][2]) > cur[-1][2] * 0.2):   # 층이 낮아지거나 금액이 크게 바뀜
            segs.append(cur)
            cur = []
        cur.append(r)
    if cur:
        segs.append(cur)
    return segs


def assign(rows, types):
    """묶음별 최고가 = 청약홈 타입별 최고 분양가 로 타입을 맞추고 단위(원·천원·만원)를 정한다."""
    tops = [(t[2], t[3]) for t in types if len(t) > 3 and t[3]]
    if not tops or not rows:
        return {}
    best = {}
    for scale in (10000, 10, 1):
        segs = _segments([[a, b, round(c / scale)] for a, b, c in rows])
        used, res, pend = set(), {}, []
        for sg in segs:
            mx = max(r[2] for r in sg)
            cand = [l for l, tp in tops if abs(tp - mx) <= 10 and l not in used]
            if cand:
                used.add(cand[0])
                res[cand[0]] = pend + sg       # 앞의 맞지 않은 작은 묶음(동·호 별도 금액)은 이 타입에 합침
                pend = []
            else:
                pend += sg
        if len(res) > len(best):
            best = res
    return best


def parse(data, types):
    """PDF → (가격표 {약식표기: [[최저층, 최고층, 만원]]}, 세대 정보)."""
    import pdfplumber
    info = {}
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = pdf.pages[:24]
        texts = [(pg.extract_text() or "") for pg in pages]
        whole = "\n".join(texts)
        m = re.search(r"공급\s*규모[^\n]*?총\s*([\d,]+)\s*세대", whole) or re.search(r"총\s*([\d,]+)\s*세대", whole)
        if m:
            info["total"] = _int(m.group(1))
        for k, pat in (("gen", r"일반\s*분양\s*([\d,]+)\s*세대"), ("mem", r"(?:토지등소유자|조합원)(?:\s*분양)?\s*([\d,]+)\s*세대"),
                       ("res", r"보류지\s*([\d,]+)\s*세대")):
            m = re.search(pat, whole)
            if m:
                info[k] = _int(m.group(1))
        idx = [i for i, t in enumerate(texts) if re.search(r"공급\s*금액|분양\s*금액|분양\s*가격|공급\s*가격", t)]
        best = {}
        for start in idx[:4]:
            rows = []
            for t in texts[start:start + 6]:
                rows += _rows(t)
            got = assign(rows, types)
            if len(got) > len(best):
                best = got
    return best, info


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
    out = {"date": today.strftime("%Y%m%d"), "ok": False, "prices": {}}
    s = requests.Session()
    s.headers.update(UA)
    try:
        for link in pdf_links(house["url"], s)[:3]:
            r = s.get(link, timeout=120)
            if r.content[:4] != b"%PDF":
                continue
            prices, info = parse(r.content, house["types"])
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
