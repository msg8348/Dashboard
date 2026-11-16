"""청약단지 메뉴 — 시도별 청약 일정·분양 단지 (site/sub/{시도}.json).

- 청약홈 분양정보(applyhome): 접수 일정·규제·타입별 공급세대·최고 분양가
- 주변 시세: 같은 시군구 최근 1년 매매 59·84타입 단지별 최고가 Top 5
- 주변 정보: 카카오(초등학교·지하철·버스·학원·음식점·카페·대형마트) — poi 캐시 키 'sub:{주택관리번호}'
"""
import json
import os
import re
from collections import defaultdict
from datetime import timedelta

import poi

PREFIX = [("서울", "11"), ("부산", "26"), ("대구", "27"), ("인천", "28"), ("광주", "12"), ("전라남", "12"), ("전남", "12"),
          ("대전", "30"), ("울산", "31"), ("세종", "36"), ("경기", "41"), ("강원", "51"), ("충청북", "43"), ("충북", "43"),
          ("충청남", "44"), ("충남", "44"), ("전라북", "52"), ("전북", "52"), ("경상북", "47"), ("경북", "47"),
          ("경상남", "48"), ("경남", "48"), ("제주", "50")]


def sido_of(addr):
    t = (addr or "").split()[0] if addr else ""
    return next((k for p, k in PREFIX if t.startswith(p)), "")


def _ty(a):
    ai = int(a)
    return "59" if ai == 59 else "74" if 70 <= ai <= 77 else "84" if ai == 84 else ""


def build(site, store, sd, sdir, sale, houses, now, alias, apt_pages, notices, cinfo=None):
    today = now.strftime("%Y%m%d")
    d60 = (now - timedelta(days=60)).strftime("%Y-%m-%d")
    d1y = (now - timedelta(days=365)).strftime("%Y%m%d")
    mine = [h for h in houses if sido_of(h.get("addr")) == sd["key"] and (h.get("pbl") or "") >= d60]
    if not mine:
        return 0
    codes = sd["codes"]

    def gu_of(addr):
        toks = addr.split()
        hit = [(c, n) for c, n in codes.items() if n.split()[-1] in toks]
        return max(hit, key=lambda x: len(x[1])) if hit else ("", "")

    # 주변 시세: 시군구 → 타입 → 단지별 최고가
    near = defaultdict(lambda: defaultdict(dict))
    for t in sale:
        if str(t["dt"]) < d1y:
            continue
        ty = _ty(t["a"])
        if ty not in ("59", "84"):
            continue
        s = t.get("s")
        to, nm = alias.get(s, (s, t["n"])) if s else (None, t["n"])
        k = to or nm
        cur = near[t.get("c")][ty].get(k)
        if not cur or t["p"] > cur[2]:
            hh, ap = cinfo(t) if cinfo else (0, "")
            ym = f"{str(ap)[2:4]}.{str(ap)[4:6]}" if ap and len(str(ap)) >= 6 else ""
            near[t.get("c")][ty][k] = [nm, t.get("u", ""), t["p"], str(t["dt"]),
                                      f"{sdir}/apt/{to}.html" if to and to in apt_pages else "", hh or 0, ym]
    # 주변 정보 (카카오)
    ppath = os.path.join(store, "poi.json")
    pc = poi.load(ppath)

    def clean(addr):
        a = re.sub(r"\(.*?\)|번지|일원|외\s*\d+\s*필지|일대", " ", addr)
        return " ".join(a.split())
    keys = [f"sub:{h['id']}" for h in mine]
    poi.update(pc, {f"sub:{h['id']}": (clean(h["addr"]), h["name"]) for h in mine}, now, budget=300)
    poi.amen(pc, keys, "a1", budget=300)
    poi.save(ppath, pc)
    out = []
    for h in mine:
        code, gname = gu_of(h["addr"])
        dong = next((w for w in h["addr"].split() if w[-1] in "동리가읍면" and not w[0].isdigit()), "")
        by = defaultdict(list)
        for t in h.get("types", []):
            if len(t) >= 4 and t[3]:
                ty = _ty(t[0])
                if ty:
                    by[ty].append(t[3])
        avg = {ty: round(sum(v) / len(v)) for ty, v in by.items()}
        cm = h.get("cmp") or {}

        def lab(ty):
            m = re.match(r"\s*0*(\d+(?:\.\d+)?)", ty)
            return f"{int(float(m.group(1)))}{re.sub(r'[^A-Za-z]', '', ty[m.end():]).upper()}" if m else ty
        cmpd = {lab(k): v for k, v in (cm.get("c") or {}).items()}
        score = {lab(k): v for k, v in (cm.get("s") or {}).items()}
        req = sum((v[1] or 0) for v in cmpd.values()); sup = sum((v[2] or 0) for v in cmpd.values())
        p = pc.get(f"sub:{h['id']}") or {}
        nt = notices.get(h["id"]) or {}
        out.append({
            "id": h["id"], "n": h["name"], "g": gname.split()[-1] if gname else "", "d": dong, "addr": h["addr"],
            "tot": h.get("total") or 0, "mv": h.get("mvn") or "", "b": h.get("builder") or "", "kind": h.get("kind") or "",
            "reg": h.get("reg") or [], "sch": h.get("sch") or {}, "pbl": (h.get("pbl") or "").replace("-", ""), "url": h.get("url") or "",
            "avg": avg, "ty": [[t[2], round(t[0], 2), t[1], t[5] if len(t) > 5 else None, t[3]] for t in h.get("types", []) if len(t) >= 4],
            "bd": nt.get("bd", 0), "fl": nt.get("fl", 0),
            "cmp": cmpd, "score": score, "cr": round(req / sup, 1) if sup and req else None,   # 1순위 해당지역 경쟁률 · 당첨 가점
            "poi": {k: p.get(k) for k in ("sc", "st", "bus", "ac", "fd", "mt") if p.get(k) is not None},
            "near": {ty: sorted(near[code][ty].values(), key=lambda x: -x[2])[:5] for ty in ("59", "84")} if code else {},
        })
    os.makedirs(os.path.join(site, "sub"), exist_ok=True)
    with open(os.path.join(site, "sub", f"{sdir}.json"), "w", encoding="utf-8") as f:
        json.dump({"today": today, "h": out}, f, ensure_ascii=False, separators=(",", ":"))
    return len(out)
