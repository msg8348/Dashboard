// 최고가 (기간·지역·평형별 단지 최고 거래 순위) — 홈 메뉴 페이지(hi.html)와 지역 페이지 '최고가' 탭 공용
// NDPHi(el, { root, sidos: [[이름, 시도]], s: 고정 시도, g: 고정 구·군, v })
(function () {
  const css = `
.hiw .sels2{display:flex;gap:6px;margin-bottom:8px}
.hiw .sels2 select{flex:1;min-width:0;font:inherit;font-size:14px;font-weight:700;height:38px;border:1px solid #d6dbe2;border-radius:10px;padding:0 8px;background:#fff;color:#17202c}
.hiw .sels2 select[hidden]{display:none}
.hiw .seg{display:flex;background:#e6e9ef;border-radius:12px;padding:3px;margin-bottom:8px}
.hiw .seg button{flex:1;font:inherit;font-size:13.5px;font-weight:800;color:#4a5566;border:0;background:none;border-radius:9px;padding:7px 0;cursor:pointer}
.hiw .seg button.on{background:#fff;color:#17202c;box-shadow:0 1px 3px rgba(20,30,60,.12)}
.hiw .r{display:flex;align-items:center;gap:10px;padding:10px 2px;border-top:1px solid #f0f2f5;text-decoration:none;color:inherit}
.hiw .rk{width:24px;height:24px;border-radius:50%;background:#eef1f6;color:#4a5566;font-size:12.5px;font-weight:800;display:grid;place-items:center;flex:none}
.hiw .rk.t3{background:#e0472c;color:#fff}
.hiw .nm{flex:1;min-width:0}
.hiw .nm b{display:flex;align-items:center;gap:5px;font-size:15px;font-weight:800;white-space:nowrap;overflow:hidden}
.hiw .nm b span{overflow:hidden;text-overflow:ellipsis}
.hiw .nm small{display:block;font-size:12px;color:#8a94a3;font-weight:400;margin-top:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hiw .pt{font-style:normal;font-size:11px;font-weight:800;color:#d12f62;background:#fde8ee;border-radius:6px;padding:1px 6px;flex:none}
.hiw .pr{text-align:right;flex:none}.hiw .pr b{display:block;font-size:16px;font-weight:800;color:#2754d6}.hiw .pr.j b{color:#0f6b5c}
.hiw .pr small{font-size:11.5px;color:#8a94a3;font-weight:400}
.hiw .empty{text-align:center;color:#8a94a3;font-size:14px;padding:34px 0;line-height:1.6;border-top:1px solid #f0f2f5}
.hiw .note{font-size:11.5px;color:#8a94a3;text-align:right;padding:6px 0 4px}`;
  const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
  const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const eok = p => { const e = Math.floor(p / 1e4), r = p % 1e4; return (e ? e + '억' : '') + (r ? (e ? ' ' : '') + r.toLocaleString() : '') || '0'; };
  const opt = (v, l, on) => `<option value="${esc(v)}"${on ? ' selected' : ''}>${esc(l)}</option>`;
  const getj = u => fetch(u).then(r => r.json());
  const idx = {}, yc = {};

  window.NDPHi = function (el, o) {
    const root = o.root || '', key = 'ndp_hi' + (o.s ? ':' + o.s + ':' + (o.g || '') : '');
    const S = { s: o.s || '', g: o.g || '', d: '', y: '', m: '', k: 's', t: 0 };
    try { Object.assign(S, JSON.parse(sessionStorage.getItem(key)) || {}); } catch (e) {}
    if (o.s) S.s = o.s;
    if (o.g) S.g = o.g;
    el.classList.add('hiw');
    el.innerHTML = `<div class="sels2"><select class="h-sido" aria-label="시도"${o.s ? ' hidden' : ''}>${(o.sidos || []).map(x => opt(x[1], x[0])).join('')}</select><select class="h-gu" aria-label="구·군"></select><select class="h-dong" aria-label="동"></select></div>
      <div class="sels2"><select class="h-yr" aria-label="연도"></select><select class="h-mo" aria-label="월"></select></div>
      <div class="seg h-kind"><button type="button" data-k="s">매매·분양권</button><button type="button" data-k="j">전세</button></div>
      <div class="seg h-ty"><button type="button" data-t="0">전체</button><button type="button" data-t="59">59</button><button type="button" data-t="74">74</button><button type="button" data-t="84">84</button></div>
      <div class="h-list"></div><div class="note h-note"></div>`;
    const $ = c => el.querySelector(c);
    const sel = $('.h-sido');
    if (!o.s) { if (S.s && [...sel.options].some(x => x.value === S.s)) sel.value = S.s; else S.s = sel.value; }

    async function render() {
      try { sessionStorage.setItem(key, JSON.stringify(S)); } catch (e) {}
      const ix = idx[S.s] = idx[S.s] || await getj(`${root}hi/${S.s}.json?v=${o.v || ''}`);
      if (!ix.y.includes(S.y)) S.y = ix.y[ix.y.length - 1] || '';   // 기본: 올해
      const gu = $('.h-gu'), dong = $('.h-dong');
      gu.hidden = !ix.g.length || !!o.g;
      gu.innerHTML = opt('', '전체', !S.g) + ix.g.map(g => opt(g, g, g === S.g)).join('');
      const ds = ix.d[S.g] || [];
      if (!ds.includes(S.d)) S.d = '';
      dong.hidden = !S.g;
      dong.innerHTML = opt('', o.g ? '동 전체' : '전체', !S.d) + ds.map(d => opt(d, d, d === S.d)).join('');
      $('.h-yr').innerHTML = ix.y.slice().reverse().map(y => opt(y, y + '년', y === S.y)).join('');
      $('.h-mo').innerHTML = opt('', '전체 월', !S.m) + Array.from({ length: 12 }, (_, i) => opt(String(i + 1), (i + 1) + '월', String(i + 1) === S.m)).join('');
      el.querySelectorAll('.h-kind button').forEach(b => b.classList.toggle('on', b.dataset.k === S.k));
      el.querySelectorAll('.h-ty button').forEach(b => b.classList.toggle('on', +b.dataset.t === +S.t));
      const list = $('.h-list');
      if (!S.y) { list.innerHTML = '<div class="empty">데이터가 없어요</div>'; return; }
      const ck = S.s + S.y;
      if (!yc[ck]) list.innerHTML = '<div class="empty">불러오는 중…</div>';
      const d = yc[ck] = yc[ck] || await getj(`${root}hi/${S.s}/${S.y}.json?v=${o.v || ''}`);
      const best = new Map();
      for (const r of d.t) {
        const [mi, kind, ty, mo, p] = r;
        if ((S.k === 'j') !== (kind === 2)) continue;
        if (+S.t && ty !== +S.t) continue;
        if (S.m && mo !== +S.m) continue;
        const m = d.m[mi];
        if (S.g && m[2] !== S.g) continue;
        if (S.d && m[3] !== S.d) continue;
        const k = mi + ':' + kind;
        if (!best.has(k) || p > best.get(k)[4]) best.set(k, r);
      }
      const rs = [...best.values()].sort((a, b) => b[4] - a[4]).slice(0, 10);
      list.innerHTML = rs.length ? rs.map(([mi, kind, ty, mo, p, f, dd, a], i) => {
        const m = d.m[mi], pre = kind === 1;
        const loc = S.d ? '' : S.g ? m[3] : m[2];   // 전체: 구·군 / 구·군 선택: 동 / 동 선택: 생략
        const sub = [loc, m[4] ? String(m[4]).slice(2) + '년' + (pre ? ' 예정' : '') : ''].filter(Boolean).join(' · ');
        const when = `${S.y.slice(2)}.${String(mo).padStart(2, '0')}.${String(dd).padStart(2, '0')}`;
        const inner = `<span class="rk ${i < 3 ? 't3' : ''}">${i + 1}</span><span class="nm"><b><span>${esc(m[1])}</span>${pre ? '<i class="pt">분양권</i>' : ''}</b><small>${esc(sub)}</small></span>`
          + `<span class="pr ${kind === 2 ? 'j' : ''}"><b>${eok(p)}</b><small>${ty || Math.round(a) + '㎡'} · ${/^-?\d+$/.test(f) ? f + '층' : esc(f)} · ${when}</small></span>`;
        return m[0].endsWith('.html') ? `<a class="r" href="${esc(root + m[0])}">${inner}</a>` : `<div class="r">${inner}</div>`;
      }).join('') : '<div class="empty">이 조건에 맞는 거래가 없어요</div>';
      $('.h-note').textContent = `국토부 실거래 · 계약일 기준 · 기간 중 단지별 최고 거래${S.k === 'j' ? ' (전세는 최근 1년)' : ''}`;
    }
    sel.onchange = () => { S.s = sel.value; S.g = S.d = ''; render(); };
    $('.h-gu').onchange = e => { S.g = e.target.value; S.d = ''; render(); };
    $('.h-dong').onchange = e => { S.d = e.target.value; render(); };
    $('.h-yr').onchange = e => { S.y = e.target.value; render(); };
    $('.h-mo').onchange = e => { S.m = e.target.value; render(); };
    $('.h-kind').onclick = e => { const b = e.target.closest('button'); if (b) { S.k = b.dataset.k; render(); } };
    $('.h-ty').onclick = e => { const b = e.target.closest('button'); if (b) { S.t = +b.dataset.t; render(); } };
    render();
  };
})();
