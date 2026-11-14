"""과거 매매 실거래 수집기 (단지 페이지용).

    python history.py --minutes 280 --max-calls 8000

2006년 1월부터 '최근 13개월 창(store/sale)' 바로 앞 달까지의 전국 아파트 매매를 받아
단지별로 모아 저장한다. 실행할 때마다 받은 데까지 저장하고, 다음 실행에서 이어 받는다.

저장 (HIST_DIR, 기본 hist/ — 워크플로에서 'history' 브랜치로 보관)
    hist/{시도코드}.json.gz = {"fetched": ["코드|연월", ...],
                               "apts": {단지키: {"n": 단지명, "c": 시군구코드, "u": 법정동, "j": 지번, "by": 건축년도,
                                                 "t": [[계약일 YYYYMMDD, 금액(만원), 층, 동, 전용면적, 등기일], ...]}}}
    단지키 = 국토부 단지 일련번호(aptSeq), 없으면 '시군구코드|법정동|지번|단지명'
"""
import argparse
import gzip
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import Dashboard as D
import regions

HIST = os.environ.get("HIST_DIR", "hist")
START = "200601"            # 국토부 실거래 공개 시작
WORKERS = int(os.environ.get("FETCH_WORKERS", "8"))
FIRST = ["26", "11", "41", "28"]   # 부산 · 서울 · 경기 · 인천 먼저


def path(key):
    return os.path.join(HIST, f"{key}.json.gz")


def load(key):
    if os.path.exists(path(key)):
        with gzip.open(path(key), "rt", encoding="utf-8") as f:
            return json.load(f)
    return {"fetched": [], "apts": {}}


def save(key, db):
    os.makedirs(HIST, exist_ok=True)
    tmp = path(key) + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as f:
        json.dump(db, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path(key))


def apt_key(t, code):
    return t.get("s") or f"{code}|{t.get('u', '')}|{t.get('j', '')}|{t['n']}"


def months_until(end_ym):
    """START ~ end_ym (포함), 최신 달부터."""
    out, y, m = [], int(end_ym[:4]), int(end_ym[4:])
    while f"{y:04d}{m:02d}" >= START:
        out.append(f"{y:04d}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def add(db, code, ym, trades):
    """그 지역·그 달 거래를 단지별로 넣음 (과거 달은 한 번만 받음)."""
    for t in trades:
        k = apt_key(t, code)
        a = db["apts"].setdefault(k, {"n": t["n"], "c": code, "u": t.get("u", ""), "j": t.get("j", ""),
                                      "by": t.get("by", ""), "t": []})
        if t.get("by") and not a.get("by"):
            a["by"] = t["by"]
        f = t.get("f", "")
        a["t"].append([int(t["dt"]), t["p"], int(f) if str(f).lstrip("-").isdigit() else f,
                       t.get("dong", ""), t["a"], t.get("rg", "")])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=280)
    ap.add_argument("--daily", type=int, default=7000, help="하루(KST) 과거 수집 호출 한도 — 매일 갱신용 한도는 남겨 둠")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    now = datetime.now(D.KST)
    end = D.month_list(now, D.WINDOW_MONTHS)[-1]          # 13개월 창의 가장 오래된 달
    y, m = int(end[:4]), int(end[4:]) - 1
    if m == 0:
        y, m = y - 1, 12
    end = f"{y:04d}{m:02d}"                                 # 그 앞 달까지가 과거 수집 범위
    months = months_until(end)
    regions.PATH = os.path.join(os.environ.get("STORE_DIR", "store"), "regions.json")
    sidos = regions.build(regions.load(now))
    sidos.sort(key=lambda s: (FIRST.index(s["key"]) if s["key"] in FIRST else 99))
    if args.only:
        sidos = [s for s in sidos if s["key"] in args.only.split(",")]
    print(f"📚 과거 매매 수집: {months[-1]} ~ {months[0]} ({len(months)}개월) · {len(sidos)}개 시도")

    # 하루 호출 예산 (같은 날 여러 번 실행해도 합계가 --daily 를 넘지 않게)
    bpath = os.path.join(HIST, "_budget.json")
    today = now.strftime("%Y%m%d")
    used = 0
    if os.path.exists(bpath):
        with open(bpath) as f:
            b = json.load(f)
        used = b.get("used", 0) if b.get("date") == today else 0
    args.max_calls = max(0, args.daily - used)
    print(f"📞 오늘 남은 과거 수집 호출 {args.max_calls}회 (한도 {args.daily})")
    started, calls, quota, total_left = time.time(), 0, False, 0
    with ThreadPoolExecutor(WORKERS) as ex:
        for sd in sidos:
            key = sd["key"]
            db = load(key)
            done = set(db["fetched"])
            tasks = [(code, name, ym) for ym in months for code, name in sd["codes"].items() if f"{code}|{ym}" not in done]
            if not tasks:
                continue
            got = errs = 0
            i = 0
            last_save = time.time()
            while i < len(tasks) and not quota:
                if calls >= args.max_calls or time.time() - started > args.minutes * 60:
                    break
                batch = tasks[i:i + WORKERS * 2]
                i += len(batch)
                futs = [(t, ex.submit(D.fetch_month, "sale", t[1], t[0], t[2])) for t in batch]
                for (code, name, ym), fut in futs:
                    calls += 1
                    try:
                        trades = fut.result()
                    except D.QuotaError as e:
                        if not quota:
                            print(f"⛔ {e} — 오늘은 여기까지, 다음 실행에서 이어 받음")
                        quota = True
                        continue
                    except D.FetchError as e:
                        errs += 1
                        if errs <= 3:
                            print("⚠️", e)
                        continue
                    add(db, code, ym, trades)
                    db["fetched"].append(f"{code}|{ym}")
                    got += 1
                if time.time() - last_save > 600:              # 10분마다 중간 저장
                    save(key, db)
                    last_save = time.time()
            save(key, db)
            left = len(tasks) - got
            total_left += left
            n = sum(len(a["t"]) for a in db["apts"].values())
            print(f"🗂️ {sd['short']}: 이번 {got}건 받음 · 남은 지역·월 {left} · 단지 {len(db['apts']):,} · 거래 {n:,}")
            if quota or calls >= args.max_calls or time.time() - started > args.minutes * 60:
                total_left += sum(1 for s in sidos[sidos.index(sd) + 1:] for _ in s["codes"]) * len(months)
                break
    os.makedirs(HIST, exist_ok=True)
    with open(bpath, "w") as f:
        json.dump({"date": today, "used": used + calls}, f)
    budget_out = used + calls >= args.daily
    print(f"✅ 호출 {calls}회 · {time.time() - started:.0f}초 · {'한도 도달' if quota or budget_out else '진행'}")
    with open("HIST_STATUS", "w") as f:
        f.write("quota" if (quota or budget_out) else ("more" if total_left else "done"))


if __name__ == "__main__":
    main()
