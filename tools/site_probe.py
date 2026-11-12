"""외부 사이트 접속·구조 진단 (저장 없음, 로그만 출력).

python tools/site_probe.py https://asil.kr/app/asil.jsp https://burupang.com
- 각 사이트 첫 화면, robots.txt 를 받아 상태와 일부 내용을 출력
- HTML 안의 스크립트 파일을 받아 데이터 요청 주소로 보이는 문자열(api, .jsp, json 등)을 추려 출력
- 약관/이용약관 링크가 있으면 해당 페이지에서 수집·크롤링 관련 문장을 출력
"""
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})


def get(url, n=300):
    t0 = time.time()
    try:
        r = S.get(url, timeout=20)
        r.encoding = r.apparent_encoding or r.encoding
        print(f"  [{r.status_code}] {time.time() - t0:.1f}s {url} ({len(r.text)} bytes, {r.headers.get('content-type', '')})")
        return r
    except requests.RequestException as e:
        print(f"  [FAIL] {time.time() - t0:.1f}s {url} {type(e).__name__}: {str(e)[:120]}")
        return None


def endpoints(text):
    pats = [r'["\'](/[A-Za-z0-9_./-]*(?:api|json|\.jsp|\.do|ajax|data)[A-Za-z0-9_./-]*)["\'?]',
            r'["\'](https?://[A-Za-z0-9.-]+/[A-Za-z0-9_./-]*(?:api|json|\.jsp|\.do|ajax)[A-Za-z0-9_./-]*)["\'?]']
    found = set()
    for p in pats:
        found.update(re.findall(p, text))
    return sorted(found)


def probe(url):
    print(f"\n========== {url} ==========")
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    r = get(url)
    get_robots = get(base + "/robots.txt")
    if get_robots is not None and get_robots.status_code == 200:
        print("  robots.txt:\n    " + get_robots.text[:600].replace("\n", "\n    "))
    if r is None or r.status_code != 200:
        return
    html = r.text
    title = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    print(f"  title: {title.group(1).strip()[:80] if title else '-'}")
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    print(f"  본문 일부: {text[:500]}")
    for kw in ["매물", "사라진", "증감", "API", "api", "로그인", "회원", "유료", "구독", "부산"]:
        if kw in html:
            i = text.find(kw)
            print(f"  키워드 '{kw}': {text[max(0, i - 60):i + 80] if i >= 0 else '(스크립트 안에만 있음)'}")
    eps = endpoints(html)
    scripts = [urljoin(url, s) for s in re.findall(r'<script[^>]+src=["\']([^"\']+)', html, re.I)]
    print(f"  스크립트 {len(scripts)}개: {scripts[:12]}")
    for s in scripts[:12]:
        if urlparse(s).netloc not in (urlparse(url).netloc, "") and "asil" not in s and "burupang" not in s:
            continue
        sr = get(s)
        if sr is not None and sr.status_code == 200:
            eps += endpoints(sr.text)
    eps = sorted(set(eps))
    print(f"  데이터 요청 주소 후보 {len(eps)}개:")
    for e in eps[:80]:
        print("    " + e)
    links = re.findall(r'href=["\']([^"\']+)["\'][^>]*>([^<]{0,30})', html)
    terms = [urljoin(url, h) for h, t in links if any(k in (h + t) for k in ["약관", "terms", "policy", "agree", "service"])]
    for t in list(dict.fromkeys(terms))[:3]:
        tr = get(t)
        if tr is not None and tr.status_code == 200:
            tt = re.sub(r"<[^>]+>", " ", tr.text)
            tt = re.sub(r"\s+", " ", tt)
            for kw in ["크롤", "스크래", "자동", "수집", "복제", "무단", "로봇", "기계적"]:
                for m in re.finditer(kw, tt):
                    print(f"    약관[{kw}]: ...{tt[max(0, m.start() - 80):m.start() + 120]}...")
                    break


if __name__ == "__main__":
    for u in sys.argv[1:]:
        probe(u)
