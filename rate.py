"""금리 (한국은행 ECOS Open API) → store/rate.json, 하루 한 번 갱신.

- 기준금리: 한국은행 기준금리 (722Y001, 일별 → 변경일만 남김)
- 주담대 평균: 예금은행 가중평균 대출금리 · 신규취급액 · 주택담보대출 (121Y006, 월별)
- 국고채 3년: 시장금리 (817Y002, 일별 → 주 끝 값)
항목 코드는 통계표의 항목 목록(StatisticItemList)에서 이름으로 찾는다 (코드가 바뀌어도 이름으로 맞춤).
ECOS_API_KEY 가 없거나 받지 못하면 예전 rate.json 그대로 둔다.
"""
import json
import os
from datetime import datetime, timedelta

import requests

API = "https://ecos.bok.or.kr/api"
KEY = os.environ.get("ECOS_API_KEY", "")
SERIES = {   # 이름: (통계표, 주기, 항목 이름에 들어갈 말들, 시작)
    "base": ("722Y001", "D", ["기준금리"], "19990501"),
    "mort": ("121Y006", "M", ["주택담보대출"], "200101"),
    "kb3": ("817Y002", "D", ["국고채", "3년"], None),
}


def _get(path):
    r = requests.get(f"{API}/{path}", timeout=30)
    r.raise_for_status()
    return r.json()


def item_code(stat, words):
    js = _get(f"StatisticItemList/{KEY}/json/kr/1/1000/{stat}")
    rows = (js.get("StatisticItemList") or {}).get("row") or []
    hits = [r for r in rows if all(w in (r.get("ITEM_NAME") or "") for w in words)]
    if not hits:
        raise ValueError(f"{stat} 항목 없음 {words}: {[r.get('ITEM_NAME') for r in rows][:30]}")
    hits.sort(key=lambda r: len(r.get("ITEM_NAME") or ""))   # 가장 짧은 이름 (예: '주택담보대출')
    print(f"  {stat} → {hits[0]['ITEM_CODE']} {hits[0]['ITEM_NAME']}")
    return hits[0]["ITEM_CODE"]


def series(stat, cycle, code, start, end):
    js = _get(f"StatisticSearch/{KEY}/json/kr/1/100000/{stat}/{cycle}/{start}/{end}/{code}")
    rows = (js.get("StatisticSearch") or {}).get("row") or []
    out = []
    for r in rows:
        try:
            out.append([r["TIME"], round(float(r["DATA_VALUE"]), 3)])
        except (KeyError, ValueError, TypeError):
            pass
    return out


def build(store, now=None):
    now = now or datetime.utcnow() + timedelta(hours=9)
    path = os.path.join(store, "rate.json")
    old = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
    today = now.strftime("%Y%m%d")
    if not KEY:
        print("💹 ECOS_API_KEY 없음 — 금리는 예전 값 사용")
        return old
    if old.get("date") == today:
        return old
    out = {"date": today}
    try:
        for name, (stat, cyc, words, start) in SERIES.items():
            code = item_code(stat, words)
            end = today if cyc == "D" else today[:6]
            if name == "kb3":
                start = (now - timedelta(days=365 * 6)).strftime("%Y%m%d")
            rows = series(stat, cyc, code, start, end)
            if name == "base":   # 바뀐 날만
                ch = []
                for d, v in rows:
                    if not ch or ch[-1][1] != v:
                        ch.append([d, v])
                out["base"] = ch
                out["base_last"] = rows[-1][0] if rows else ""
            elif name == "kb3":   # 주 끝 값 + 마지막 값
                wk = {}
                for d, v in rows:
                    dt = datetime.strptime(d, "%Y%m%d")
                    wk[(dt - timedelta(days=dt.weekday())).strftime("%Y%m%d")] = [d, v]
                out["kb3"] = sorted(wk.values())
            else:
                out[name] = rows
            print(f"💹 {name}: {len(out[name])}개 · 마지막 {out[name][-1] if out[name] else '-'}")
    except Exception as e:
        print(f"⚠️ 금리 받기 실패 — 예전 값 사용: {e}")
        return old
    os.makedirs(store, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    return out


if __name__ == "__main__":
    build(os.environ.get("STORE_DIR", "store"))
