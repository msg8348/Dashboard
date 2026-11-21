// 단지 검색: 아래에서 올라오는 검색창 + 최근 검색 기록(이 기기에만 저장). 모든 페이지 공용.
(function () {
  const me = document.currentScript, ROOT = me ? me.src.replace(/search\.js(\?.*)?$/, '') : '/';
  const KEY = 'ndp_recent';
  const CLOCK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>';
  const HOME = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round"><path d="M3.5 11L12 4l8.5 7"/><path d="M6 9.5V20h12V9.5"/></svg>';
  const css = `
.sdim{position:fixed;inset:0;background:rgba(15,22,40,.45);z-index:60}
.ssheet{position:fixed;left:0;right:0;bottom:0;margin:0 auto;max-width:720px;height:80vh;height:80dvh;background:#fff;border-radius:24px 24px 0 0;z-index:61;padding:10px 16px 16px;transform:translateY(105%);transition:transform .28s ease;display:flex;flex-direction:column;font-family:'Pretendard','Apple SD Gothic Neo','Malgun Gothic',sans-serif;color:#17202c;visibility:hidden}
.ssheet.open{transform:none;visibility:visible}
.ssheet .grab{width:44px;height:5px;background:#d9dee6;border-radius:3px;margin:0 auto 12px;flex:none}
.ssheet .srow{display:flex;align-items:center;gap:4px;flex:none}
.ssheet .sback,.ssheet .sgo{width:40px;height:40px;border:0;background:none;display:grid;place-items:center;color:#17202c;cursor:pointer;flex:none;padding:0}
.ssheet .sback svg{width:26px;height:26px}.ssheet .sgo svg{width:24px;height:24px}
.ssheet .sbox{flex:1;display:flex;align-items:center;background:#f0f1f3;border-radius:14px;padding:0 8px 0 14px;min-width:0}
.ssheet .sbox input{flex:1;border:0;outline:0;background:transparent;font:inherit;font-size:16.5px;padding:12px 0;min-width:0;color:#17202c}
.ssheet .sclr{width:24px;height:24px;border-radius:50%;border:0;background:#8f949c;color:#fff;font-size:17px;line-height:1;display:grid;place-items:center;cursor:pointer;flex:none;padding:0}
.ssheet .sclr[hidden]{display:none}
.ssheet .sres{overflow:auto;margin-top:12px;-webkit-overflow-scrolling:touch}
.ssheet .sh{display:flex;justify-content:space-between;align-items:center;font-size:13px;font-weight:800;color:#4a5566;margin:4px 2px 6px}
.ssheet .sh button{border:0;background:none;font:inherit;font-size:12.5px;color:#8a94a3;font-weight:700;cursor:pointer}
.ssheet .si{display:flex;align-items:center;gap:10px;padding:11px 4px;border-bottom:1px solid #f0f2f5;cursor:pointer;text-decoration:none;color:inherit}
.ssheet .si .ic{width:30px;height:30px;border-radius:50%;background:#f1f3f6;display:grid;place-items:center;flex:none;color:#4a5566}.ssheet .si .ic svg{width:15px;height:15px}
.ssheet .si b{display:block;font-size:15.5px;font-weight:800}.ssheet .si b u{text-decoration:none;color:#2754d6}
.ssheet .si small{display:block;font-size:12.5px;color:#8a94a3;margin-top:1px}
.ssheet .si .t{flex:1;min-width:0}.ssheet .si .del{border:0;background:none;color:#b4bcc8;font-size:20px;padding:4px 8px;cursor:pointer}
.ssheet .empty2{text-align:center;color:#8a94a3;font-size:14px;padding:30px 0;line-height:1.6}`;
  // ---- 관심단지 (이 기기에 저장): [[단지명, 위치, 주소(시도/apt/번호.html)], ...]
  const FKEY = 'ndp_fav';
  const Fav = {
    get() { try { return JSON.parse(localStorage.getItem(FKEY)) || []; } catch (e) { return []; } },
    set(a) { try { localStorage.setItem(FKEY, JSON.stringify(a)); } catch (e) {} Push.later(); },
    has(p) { return Fav.get().some(x => x[2] === p); },
    add(it) { if (!Fav.has(it[2])) Fav.set([it, ...Fav.get()]); },
    remove(p) { Fav.set(Fav.get().filter(x => x[2] !== p)); },
    toggle(it) { if (Fav.has(it[2])) { Fav.remove(it[2]); return false; } Fav.add(it); return true; },
  };
  // 입주 후 매매 단지로 옮겨 간 분양권: 관심단지에 남은 예전 분양권 주소를 새 단지 주소·이름으로 바꿈 (하루 한 번)
  const SJS = (document.currentScript && document.currentScript.src) || '';
  Fav.migrate = async (root) => {
    const l = Fav.get();
    if (!l.some(x => x[2].includes('/pre/'))) return false;
    const day = new Date().toISOString().slice(0, 10);
    let mv;
    const url = SJS ? new URL(`moved.json?v=${day}`, SJS).href : `${root || ''}moved.json?v=${day}`;
    try { mv = await fetch(url).then(r => r.ok ? r.json() : {}); } catch (e) { return false; }
    let ch = false;
    const out = [];
    for (const x of l) {
      const m = mv[x[2]];
      if (m) { ch = true; if (!out.some(y => y[2] === m[0]) && !l.some(y => y[2] === m[0])) out.push([m[1], m[2], m[0]]); }
      else out.push(x);
    }
    if (ch) Fav.set(out);
    return ch;
  };
  window.NDPFav = Fav;
  try { if (sessionStorage.getItem('ndp_mig') !== new Date().toDateString()) { sessionStorage.setItem('ndp_mig', new Date().toDateString()); Fav.migrate().then(ch => { if (ch) window.dispatchEvent(new Event('ndpfav')); }); } } catch (e) {}
  // ---- 알림: 이 기기의 선택(ndp_notify)과 관심단지를 알림 서버에 저장 (cloudflare/push)
  const PUSH_API = 'https://nextdoorprice-push.newreds22.workers.dev';
  const nGet = () => { try { return JSON.parse(localStorage.getItem('ndp_notify')) || {}; } catch (e) { return {}; } };
  const u8 = s => { s = s.replace(/-/g, '+').replace(/_/g, '/'); const b = atob(s + '='.repeat((4 - s.length % 4) % 4)); return Uint8Array.from(b, c => c.charCodeAt(0)); };
  let pushT;
  const Push = {
    later() { clearTimeout(pushT); pushT = setTimeout(() => Push.sync().catch(() => {}), 800); },   // 관심단지가 바뀌면 서버에도 반영
    async sync(create) {
      if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) return 'unsupported';
      const v = nGet(), on = v.fav || v.daily;
      const reg = await navigator.serviceWorker.getRegistration();
      if (!reg) return 'no-sw';
      let sub = await reg.pushManager.getSubscription();
      if (!on) {   // 알림 끔 → 서버에서 지우고 구독 해제
        if (sub) { await fetch(PUSH_API + '/unsub', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ endpoint: sub.endpoint }) }).catch(() => {}); await sub.unsubscribe().catch(() => {}); }
        return 'off';
      }
      if (Notification.permission !== 'granted') return 'denied';
      if (!sub) {
        if (!create) return 'none';
        const { key } = await (await fetch(PUSH_API + '/vapid')).json();
        sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: u8(key) });
      }
      const r = await fetch(PUSH_API + '/sub', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sub: sub.toJSON(), favOn: !!v.fav, fav: Fav.get().map(x => x[2]), daily: !!v.daily, region: v.region || '', rname: v.rname || '' }) });
      return r.ok ? 'ok' : 'server';
    },
  };
  window.NDPPush = Push;
  // ---- 인기단지 '실시간 검색': 단지·분양권 페이지를 보면 서버에 1회 기록 (같은 기기·같은 단지는 하루 한 번, 개인 정보 없음)
  (function hit() {
    const m = window.PAGE_META;
    if (!m || !m.p || !navigator.sendBeacon) return;
    const day = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10), k = 'ndp_hit';
    let seen = {};
    try { seen = JSON.parse(localStorage.getItem(k)) || {}; } catch (e) {}
    if (seen.d !== day) seen = { d: day, p: [] };
    if (seen.p.includes(m.p)) return;
    seen.p.push(m.p);
    try { localStorage.setItem(k, JSON.stringify(seen)); } catch (e) {}
    navigator.sendBeacon(PUSH_API + '/hit', new Blob([JSON.stringify(m)], { type: 'text/plain' }));
  })();
  window.NDPRoot = ROOT;
  // ---- 오른쪽 위 ☰ 메뉴: 모든 페이지 같은 구성 (홈화면 + 홈 메뉴 8개)
  (() => {
    const ITEMS = [["index.html", "<svg viewBox=\"0 0 32 32\"><path d=\"M5 15 L16 6 L27 15 V26 H5 Z\" fill=\"#dbe5ff\" stroke=\"#2b3a67\" stroke-width=\"2.4\" stroke-linejoin=\"round\"/><rect x=\"13\" y=\"18\" width=\"6\" height=\"8\" rx=\"1\" fill=\"#2b3a67\"/></svg>", "홈화면"], ["major.html", "<svg viewBox=\"0 0 32 32\"><rect x=\"6\" y=\"4.5\" width=\"20\" height=\"23\" rx=\"3.5\" fill=\"#dbe5ff\"/><rect x=\"6\" y=\"4.5\" width=\"20\" height=\"23\" rx=\"3.5\" fill=\"none\" stroke=\"#2754d6\" stroke-width=\"2.4\"/><path d=\"M11 11.5h10M11 16h10M11 20.5h6\" stroke=\"#2754d6\" stroke-width=\"2.4\" stroke-linecap=\"round\"/></svg>", "주요거래"], ["hi.html", "<svg viewBox=\"0 0 32 32\"><rect x=\"5\" y=\"19\" width=\"5\" height=\"8\" rx=\"1.5\" fill=\"#f6c7bc\"/><rect x=\"13.5\" y=\"14\" width=\"5\" height=\"13\" rx=\"1.5\" fill=\"#f6c7bc\"/><rect x=\"22\" y=\"8\" width=\"5\" height=\"19\" rx=\"1.5\" fill=\"#e0472c\"/><path d=\"M5 14l7-6 5 3 7-7\" fill=\"none\" stroke=\"#e0472c\" stroke-width=\"2.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/></svg>", "최고가"], ["weekly.html", "<svg viewBox=\"0 0 32 32\"><rect x=\"4\" y=\"5\" width=\"11\" height=\"10\" rx=\"2.5\" fill=\"#f6c7bc\"/><rect x=\"17\" y=\"5\" width=\"11\" height=\"10\" rx=\"2.5\" fill=\"#e0472c\"/><rect x=\"4\" y=\"17\" width=\"11\" height=\"10\" rx=\"2.5\" fill=\"#2754d6\"/><rect x=\"17\" y=\"17\" width=\"11\" height=\"10\" rx=\"2.5\" fill=\"#c9d6f7\"/></svg>", "주간변동률"], ["act.html", "<svg viewBox=\"0 0 32 32\"><path d=\"M3 17h6l3-8 5 15 4-11 2 4h6\" fill=\"none\" stroke=\"#12806b\" stroke-width=\"2.8\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/></svg>", "거래활발도"], ["pop.html", "<svg viewBox=\"5 2 22 24\"><path d=\"M16 3.5c1 4.5 6.5 7 6.5 13.5a6.5 6.5 0 0 1-13 0c0-3 1.5-5 3-6.5.3 2 1.3 3.2 2.6 3.7C14 10.5 15 7 16 3.5z\" fill=\"#f97316\"/><path d=\"M16 15c.6 2 3 3 3 5.6a3 3 0 0 1-6 0c0-1.6 1-2.6 1.8-3.3.2.9.6 1.4 1.2 1.6-.3-1.4-.4-2.6 0-3.9z\" fill=\"#fed7aa\"/></svg>", "인기단지"], ["sub.html", "<svg viewBox=\"0 0 32 32\"><rect x=\"7\" y=\"9\" width=\"12\" height=\"18\" rx=\"1.5\" fill=\"#d9cffb\"/><rect x=\"17\" y=\"14\" width=\"9\" height=\"13\" rx=\"1.5\" fill=\"#7048e8\"/><path d=\"M10 13h2M14 13h2M10 17h2M14 17h2M10 21h2M14 21h2\" stroke=\"#7048e8\" stroke-width=\"1.8\" stroke-linecap=\"round\"/><path d=\"M13 9V3.5l6 2-6 2\" fill=\"#7048e8\" stroke=\"#7048e8\" stroke-width=\"1.4\" stroke-linejoin=\"round\"/></svg>", "청약단지"], ["rate.html", "<svg viewBox=\"0 0 32 32\"><circle cx=\"16\" cy=\"16\" r=\"11\" fill=\"#cdeef5\"/><path d=\"M21.5 10.5l-11 11\" stroke=\"#0e7490\" stroke-width=\"2.8\" stroke-linecap=\"round\"/><circle cx=\"11.5\" cy=\"11.5\" r=\"2.6\" fill=\"#0e7490\"/><circle cx=\"20.5\" cy=\"20.5\" r=\"2.6\" fill=\"#0e7490\"/></svg>", "금리"], ["budget.html", "<svg viewBox=\"0 0 32 32\"><rect x=\"4\" y=\"9\" width=\"24\" height=\"17\" rx=\"3.5\" fill=\"#f6dfb9\"/><path d=\"M7 9l13-4 2 4\" fill=\"none\" stroke=\"#c27512\" stroke-width=\"2\" stroke-linejoin=\"round\"/><rect x=\"18\" y=\"14\" width=\"10\" height=\"7\" rx=\"2.5\" fill=\"#c27512\"/><circle cx=\"22\" cy=\"17.5\" r=\"1.5\" fill=\"#fff\"/></svg>", "나의 예산"]];
    const mcss = `.ndm-dim{position:fixed;inset:0;background:rgba(15,22,40,.45);z-index:60}.ndm-dim[hidden]{display:none}
.ndm{position:fixed;top:0;right:0;height:100%;width:min(320px,82vw);background:#fff;z-index:61;transform:translateX(100%);transition:transform .25s ease;box-shadow:-8px 0 30px rgba(20,30,60,.18);overflow:auto;font-family:Pretendard,'Apple SD Gothic Neo','Malgun Gothic',sans-serif}
.ndm.open{transform:none}
.ndm-top{display:flex;justify-content:space-between;align-items:center;padding:14px 14px 10px 24px;font-size:18px;color:#17202c}
.ndm-x{width:40px;height:40px;border:0;background:transparent;display:grid;place-items:center;cursor:pointer;color:#17202c}.ndm-x svg{width:24px;height:24px}
.ndm-list{border-top:1px solid #e6eaf0;padding:4px 0 24px}
.ndm-it{display:flex;align-items:center;gap:12px;padding:10px 24px;font-size:16px;font-weight:700;color:#17202c;text-decoration:none}.ndm-it:hover{background:#f4f6fa}
.ndm-it .l{flex:1}.ndm-it em{font-style:normal;font-size:13px;color:#8a94a3}
.ndm-ic{width:38px;height:38px;border-radius:12px;background:#f2f4f7;display:grid;place-items:center;flex:none}.ndm-ic svg{width:22px;height:22px}
.ndm-btns{display:inline-flex;align-items:center;gap:8px}`;
    const st = document.createElement('style'); st.textContent = mcss; document.head.appendChild(st);
    const box = document.createElement('div');
    box.innerHTML = `<div class="ndm-dim" hidden></div><aside class="ndm" aria-hidden="true" aria-label="메뉴"><div class="ndm-top"><b>메뉴</b><button class="ndm-x" type="button" aria-label="닫기"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>`
      + `<div class="ndm-list">${ITEMS.map(([h, ic, l]) => `<a class="ndm-it" href="${ROOT}${h}"><span class="ndm-ic">${ic}</span><span class="l">${l}</span><em>›</em></a>`).join('')}</div></aside>`;
    document.body.appendChild(box);
    const dim = box.querySelector('.ndm-dim'), dr = box.querySelector('.ndm');
    window.openMenu = () => { dim.hidden = false; dr.classList.add('open'); dr.setAttribute('aria-hidden', 'false'); };
    window.closeMenu = () => { dim.hidden = true; dr.classList.remove('open'); dr.setAttribute('aria-hidden', 'true'); };
    dim.onclick = window.closeMenu; box.querySelector('.ndm-x').onclick = window.closeMenu;
    document.addEventListener('keydown', e => { if (e.key === 'Escape') window.closeMenu(); });
    // 오른쪽 위 버튼 줄: 하위 페이지는 모두 ★ 관심단지 · 🔍 단지 검색 · ☰ 메뉴 (홈은 ☰ 만 — 검색·즐겨찾기는 본문에 있음)
    const bar = document.querySelector('.topbar, .top');
    if (bar) {
      const isHome = !!document.querySelector('.srow');
      const ICON = {
        fav: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M12 3.6l2.6 5.3 5.8.8-4.2 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.2-4.1 5.8-.8z"/></svg>',
        search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>',
        menu: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16M4 12h16M4 18h16"/></svg>' };
      const old = [...bar.querySelectorAll('a, button')].filter(x => !x.closest('.brand'));
      const cls = ((old[0] && old[0].className) || 'menu-btn').replace(/\bon\b/, '').trim();
      const holder = (old[0] && old[0].parentElement !== bar) ? old[0].parentElement : null;
      old.forEach(x => x.remove());
      const mk = (k) => {
        const e = document.createElement(k === 'fav' ? 'a' : 'button');
        e.className = cls; e.innerHTML = ICON[k];
        e.querySelector('svg').classList.add('ic');
        if (k === 'fav') { e.href = ROOT + 'fav.html'; e.setAttribute('aria-label', '관심단지'); if (/\/fav\.html/.test(location.pathname)) e.classList.add('on'); }
        else { e.type = 'button'; e.setAttribute('aria-label', k === 'menu' ? '메뉴' : '단지 검색'); e.onclick = () => (k === 'menu' ? window.openMenu() : window.openSearch && window.openSearch()); }
        return e;
      };
      const box = holder || (() => { const w = document.createElement('span'); w.className = 'ndm-btns'; bar.appendChild(w); return w; })();
      (isHome ? ['menu'] : ['fav', 'search', 'menu']).forEach(k => box.appendChild(mk(k)));
      if (!holder) box.style.display = 'inline-flex';
    }
  })();
  // 단지·분양권 페이지의 별 버튼 (data-fav='[이름, 위치, 주소]')
  document.querySelectorAll('[data-fav]').forEach(b => {
    const it = JSON.parse(b.dataset.fav);
    const paint = () => { const on = Fav.has(it[2]); b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); b.setAttribute('aria-label', on ? '관심단지 해제' : '관심단지 추가'); };
    b.onclick = () => { Fav.toggle(it); paint(); };
    window.addEventListener('ndpfav', paint);   // 예전 분양권 주소가 새 단지 주소로 바뀌었을 때
    paint();
  });
  const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
  const wrap = document.createElement('div');
  wrap.innerHTML = `<div class="sdim" hidden></div><div class="ssheet" role="dialog" aria-label="단지 검색"><div class="grab"></div><div class="srow">
<button class="sback" type="button" aria-label="뒤로"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 5l-7 7 7 7"/></svg></button>
<div class="sbox"><input placeholder="단지명 검색" autocomplete="off" enterkeyhint="search" aria-label="단지명"><button class="sclr" type="button" aria-label="지우기" hidden>×</button></div>
<button class="sgo" type="button" aria-label="검색"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg></button>
</div><div class="sres"></div></div>`;
  document.body.appendChild(wrap);
  const dim = wrap.querySelector('.sdim'), sheet = wrap.querySelector('.ssheet'), inp = wrap.querySelector('input'),
    clr = wrap.querySelector('.sclr'), res = wrap.querySelector('.sres');
  let LIST = null, hits = [];
  // 영문·한글 브랜드 표기를 하나로 (SK뷰 = 에스케이뷰, e편한세상 = 이편한세상 …) — 단지명·검색어 모두에 적용
  const ALIAS = [['에스케이', 'sk'], ['이편한', 'e편한'], ['아이파크', 'ipark'], ['지에스', 'gs'], ['엘에이치', 'lh'], ['케이씨씨', 'kcc'],
    ['더샵', 'thesharp'], ['자이', 'xi'], ['힐스테이트', 'hillstate'], ['푸르지오', 'prugio'], ['래미안', 'raemian'],
    ['롯데캐슬', 'lottecastle'], ['뷰', 'view'], ['파크', 'park'], ['시티', 'city'], ['타워', 'tower']];
  const norm = s => {
    let t = s.replace(/[\s()\-·.,_]/g, '').toLowerCase();
    for (const [ko, en] of ALIAS) t = t.split(en).join(ko);
    return t;
  };
  const esc = s => s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const getRecent = () => { try { return JSON.parse(localStorage.getItem(KEY)) || []; } catch (e) { return []; } };
  const setRecent = a => { try { localStorage.setItem(KEY, JSON.stringify(a.slice(0, 10))); } catch (e) {} };
  function load() {
    if (LIST) return Promise.resolve(LIST);
    return fetch(ROOT + 'search.json').then(r => r.json()).then(j => (LIST = j.map(a => a.concat(norm(a[0]))))).catch(() => (LIST = []));
  }
  function hl(name, q) {
    const i = name.indexOf(q);
    return i < 0 ? esc(name) : esc(name.slice(0, i)) + '<u>' + esc(q) + '</u>' + esc(name.slice(i + q.length));
  }
  function render() {
    const raw = inp.value.trim(), q = norm(raw);
    clr.hidden = !inp.value;
    if (!q) {
      const r = getRecent();
      res.innerHTML = r.length
        ? '<div class="sh">최근 검색<button type="button" data-clear>전체 삭제</button></div>' +
          r.map((a, i) => `<div class="si" data-r="${i}"><span class="ic">${CLOCK}</span><span class="t"><b>${esc(a[0])}</b><small>${esc(a[1])}</small></span><button class="del" type="button" data-del="${i}" aria-label="삭제">×</button></div>`).join('')
        : '<div class="empty2">단지명을 입력하세요<br><small>현재 서울·경기·인천·부산·대구 단지를 제공합니다</small></div>';
      return;
    }
    if (!LIST) { res.innerHTML = '<div class="empty2">불러오는 중…</div>'; load().then(render); return; }
    hits = LIST.filter(a => a[4].includes(q)).sort((a, b) => (b[4].startsWith(q) - a[4].startsWith(q)) || b[3] - a[3]).slice(0, 60);
    res.innerHTML = hits.length
      ? hits.map((a, i) => `<div class="si" data-h="${i}"><span class="ic">${HOME}</span><span class="t"><b>${hl(a[0], raw)}</b><small>${esc(a[1])}</small></span></div>`).join('')
      : `<div class="empty2">'${esc(raw)}' 검색 결과가 없습니다<br><small>현재 서울·경기·인천·부산·대구 단지를 제공합니다</small></div>`;
  }
  let pickFn = null;                       // 관심단지 추가 모드: 결과를 누르면 이동 대신 추가
  function go(a) {
    if (pickFn) { const f = pickFn; close(); f([a[0], a[1], a[2]]); return; }
    setRecent([[a[0], a[1], a[2]], ...getRecent().filter(x => x[2] !== a[2])]);
    location.href = ROOT + a[2];
  }
  res.addEventListener('click', e => {
    const t = e.target.closest('[data-clear],[data-del],[data-r],[data-h]');
    if (!t) return;
    if (t.dataset.clear !== undefined) { setRecent([]); render(); }
    else if (t.dataset.del !== undefined) { e.stopPropagation(); const r = getRecent(); r.splice(+t.dataset.del, 1); setRecent(r); render(); }
    else if (t.dataset.r !== undefined) go(getRecent()[+t.dataset.r]);
    else go(hits[+t.dataset.h]);
  });
  function close() { dim.hidden = true; sheet.classList.remove('open'); inp.blur(); pickFn = null; inp.placeholder = '단지명 검색'; }
  window.openSearch = function (pick) {
    pickFn = typeof pick === 'function' ? pick : null;
    inp.placeholder = pickFn ? '추가할 단지명 검색' : '단지명 검색';
    dim.hidden = false; sheet.classList.add('open'); inp.value = ''; render(); load();
    setTimeout(() => inp.focus(), 250);
  };
  window.closeSearch = close;
  dim.onclick = close;
  wrap.querySelector('.sback').onclick = close;
  clr.onclick = () => { inp.value = ''; render(); inp.focus(); };
  const submit = () => { if (inp.value.trim() && hits.length) go(hits[0]); };
  wrap.querySelector('.sgo').onclick = submit;
  inp.addEventListener('input', render);
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); if (e.key === 'Escape') close(); });
})();

// 맨 위로 버튼: 아래로 내려가 있다가 위로 스크롤하면 오른쪽 아래에 나타남. 모든 페이지 공용.
(function () {
  const st = document.createElement('style');
  st.textContent = `
.totop{position:fixed;right:16px;bottom:calc(20px + env(safe-area-inset-bottom));width:48px;height:48px;border-radius:14px;border:1px solid #d6dbe2;background:rgba(255,255,255,.92);-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);color:#5b6472;display:grid;place-items:center;padding:0;cursor:pointer;z-index:19;box-shadow:0 2px 10px rgba(20,30,60,.08);opacity:0;transform:translateY(12px);pointer-events:none;transition:opacity .2s,transform .2s,bottom .3s ease}
.totop.show{opacity:1;transform:none;pointer-events:auto}
.totop svg{width:24px;height:24px}
.totop.nav{bottom:calc(84px + env(safe-area-inset-bottom))}`;
  document.head.appendChild(st);
  const b = document.createElement('button');
  b.className = 'totop'; b.type = 'button'; b.setAttribute('aria-label', '맨 위로');
  b.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20V4"/><path d="M5 11l7-7 7 7"/></svg>';
  b.onclick = () => window.scrollTo({ top: 0, behavior: 'smooth' });
  const add = () => document.body.appendChild(b);
  document.body ? add() : document.addEventListener('DOMContentLoaded', add);
  let last = window.scrollY, hideT;
  window.addEventListener('scroll', () => {
    const y = window.scrollY, nav = document.getElementById('bnav');
    b.classList.toggle('nav', !!nav && !nav.classList.contains('hide'));   // 아래 탭 막대가 보이면 그 위로
    if (y < 300) b.classList.remove('show');
    else if (y < last - 4) b.classList.add('show');     // 위로 스크롤
    else if (y > last + 4) b.classList.remove('show');  // 아래로 스크롤
    if (Math.abs(y - last) > 4) last = y;
    clearTimeout(hideT); hideT = setTimeout(() => b.classList.remove('show'), 3000);   // 멈추고 3초 지나면 숨김
  }, { passive: true });
})();
