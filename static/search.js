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
    set(a) { try { localStorage.setItem(FKEY, JSON.stringify(a)); } catch (e) {} },
    has(p) { return Fav.get().some(x => x[2] === p); },
    add(it) { if (!Fav.has(it[2])) Fav.set([it, ...Fav.get()]); },
    remove(p) { Fav.set(Fav.get().filter(x => x[2] !== p)); },
    toggle(it) { if (Fav.has(it[2])) { Fav.remove(it[2]); return false; } Fav.add(it); return true; },
  };
  window.NDPFav = Fav;
  window.NDPRoot = ROOT;
  // 단지·분양권 페이지의 별 버튼 (data-fav='[이름, 위치, 주소]')
  document.querySelectorAll('[data-fav]').forEach(b => {
    const it = JSON.parse(b.dataset.fav);
    const paint = () => { const on = Fav.has(it[2]); b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); b.setAttribute('aria-label', on ? '관심단지 해제' : '관심단지 추가'); };
    b.onclick = () => { Fav.toggle(it); paint(); };
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
        : '<div class="empty2">단지명을 입력하세요<br><small>현재 부산 단지부터 제공합니다</small></div>';
      return;
    }
    if (!LIST) { res.innerHTML = '<div class="empty2">불러오는 중…</div>'; load().then(render); return; }
    hits = LIST.filter(a => a[4].includes(q)).sort((a, b) => (b[4].startsWith(q) - a[4].startsWith(q)) || b[3] - a[3]).slice(0, 60);
    res.innerHTML = hits.length
      ? hits.map((a, i) => `<div class="si" data-h="${i}"><span class="ic">${HOME}</span><span class="t"><b>${hl(a[0], raw)}</b><small>${esc(a[1])}</small></span></div>`).join('')
      : `<div class="empty2">'${esc(raw)}' 검색 결과가 없습니다<br><small>현재 부산 단지부터 제공합니다</small></div>`;
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
