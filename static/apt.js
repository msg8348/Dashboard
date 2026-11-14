// 단지 페이지: 평형 선택 · 월평균 그래프(한 손가락=그 달, 두 손가락/끌기=기간 수익률) · 매매/전월세 표 · 거래 활발도
(function () {
  const D = JSON.parse(document.getElementById('adata').textContent);
  const S = D.s || [], R = D.r || [];                      // S: [계약일, 금액, 층, 동, 면적, 등기]  R: [계약일, 보증금, 월세, 층, 면적]
  const $ = id => document.getElementById(id);
  const won = v => { const e = Math.floor(v / 10000), r = v % 10000; return (e ? e + '억' : '') + (r ? (e ? ' ' : '') + r.toLocaleString() : '') || '0'; };
  const eok = v => (Math.round(v / 1000) / 10).toFixed(1) + '억';
  const dL = d => { const s = String(d); return `${s.slice(2, 4)}.${s.slice(4, 6)}.${s.slice(6, 8)}`; };
  const ymL = ym => { const s = String(ym); return `${s.slice(2, 4)}.${s.slice(4, 6)}`; };
  const ymOf = d => Math.floor(d / 100);
  const mIdx = ym => Math.floor(ym / 100) * 12 + (ym % 100) - 1;
  const mdiff = (a, b) => { const n = mIdx(b) - mIdx(a), y = Math.floor(n / 12), m = n % 12; return (y ? y + '년' : '') + (m ? m + '개월' : '') || '0개월'; };
  const ago = days => { const t = new Date(+TODAY.slice(0, 4), +TODAY.slice(4, 6) - 1, +TODAY.slice(6, 8) - days); return t.getFullYear() * 10000 + (t.getMonth() + 1) * 100 + t.getDate(); };
  const d365 = ago(365), d92 = ago(92);
  const grp = a => String(Math.floor(a));
  const dong = v => !v ? '' : /^\d+$/.test(v) ? v + '동 ' : v + ' ';

  // ---- 평형(전용면적 정수) 목록: 기본은 84
  const cnt = {};
  S.forEach(t => { const g = grp(t[4]); cnt[g] = (cnt[g] || 0) + 1; });
  R.forEach(t => { const g = grp(t[4]); if (!(g in cnt)) cnt[g] = 0; });
  const TYPES = Object.keys(cnt).sort((a, b) => a - b);
  let cur = cnt['84'] ? '84' : TYPES.slice().sort((a, b) => cnt[b] - cnt[a])[0];
  let shown = 10, rshown = 10;
  const isCur = t => cur === 'all' || grp(t[4]) === cur;
  const curL = () => cur === 'all' ? '전체 평형' : cur + '㎡';
  // 신고가 = 같은 평형에서 그때까지의 최고가를 넘은 거래 (전체 보기에서도 평형별로 판단)
  const HI = new Set(), AREAS = {};
  { const best = {}; S.slice().reverse().forEach(t => { const g = grp(t[4]); if (t[1] > (best[g] || 0)) { if (best[g]) HI.add(t); best[g] = t[1]; } }); }
  S.concat(R).forEach(t => (AREAS[grp(t[4])] = AREAS[grp(t[4])] || new Set()).add(t[4]));

  function drawTypes() {
    $('types').innerHTML = TYPES.length > 1 ? ['all', ...TYPES].map(k => `<button type="button" class="${k === cur ? 'on' : ''}" data-k="${k}">${k === 'all' ? '전체' : k + '㎡'}</button>`).join('') : '';
    $('types').querySelectorAll('button').forEach(b => b.onclick = () => { cur = b.dataset.k; shown = rshown = 10; draw(); });
  }

  function draw() {
    drawTypes();
    const T = S.filter(isCur);              // 최신순 (전체 = 모든 평형)
    const tyL = t => (D.by >= 2020 && AREAS[grp(t[4])].size > 1) ? `${t[4]}㎡` : grp(t[4]);   // 2020년 이후 단지에서 면적이 여러 개면 면적 그대로
    // 통계
    if (T.length) {
      const last = T[0], max = T.reduce((a, b) => b[1] > a[1] ? b : a), y1 = T.filter(t => t[0] >= d365).length;
      const first = T[T.length - 1][0];
      $('stats').innerHTML = `<div><small>최근 거래</small><b>${won(last[1])}</b><em>${dL(last[0])} · ${last[2]}층</em></div>` +
        `<div><small>최고가</small><b class="r">${won(max[1])}</b><em>${dL(max[0])} · ${max[2]}층</em></div>` +
        `<div><small>1년 거래</small><b class="k">${y1}건</b><em>최근 12개월</em></div>` +
        `<div><small>전체 거래</small><b class="k">${T.length.toLocaleString()}건</b><em>${String(first).slice(0, 4)}년 이후</em></div>`;
      $('srange').textContent = `${String(first).slice(0, 4)}.${String(first).slice(4, 6)} ~ ${String(last[0]).slice(0, 4)}.${String(last[0]).slice(4, 6)}`;
    } else {
      $('stats').innerHTML = '';
      $('srange').textContent = '';
    }
    chart(T);
    // 표: 신고가 = 그때까지의 최고가를 넘은 거래
    $('rows').innerHTML = T.length ? T.slice(0, shown).map(t => `<tr><td>${dL(t[0])}</td><td class="p">${HI.has(t) ? '<span class="stk">신고가</span>' : ''}${won(t[1])}</td>` +
      `<td>${dong(t[3])}${t[2]}층</td><td class="ty">${tyL(t)}</td><td class="g">${t[5] ? '<span class="ok">✓</span>' : ''}</td></tr>`).join('')
      : `<tr><td colspan="5" class="none">${curL()} 매매 거래가 없습니다</td></tr>`;
    const mb = $('more');
    mb.style.display = shown < T.length ? '' : 'none';
    mb.textContent = `더보기 (${(T.length - shown).toLocaleString()}건 남음)`;
    mb.onclick = () => { shown += 20; draw(); };
    rent(T);
  }

  // ---- 전월세 (최근 13개월, 선택 평형)
  function rent(T) {
    const RT = R.filter(isCur), J = RT.filter(t => !t[2]);
    $('rtype').textContent = curL();
    const avg = a => a.length ? a.reduce((s, x) => s + x, 0) / a.length : 0;
    let ja = avg(J.filter(t => t[0] >= d92).map(t => t[1])), sa = avg(T.filter(t => t[0] >= d92).map(t => t[1]));
    if (!ja || !sa) { ja = avg(J.map(t => t[1])); sa = avg(T.filter(t => t[0] >= d365).map(t => t[1])); }
    const jmax = J.reduce((a, b) => !a || b[1] > a[1] ? b : a, null);
    const y1 = RT.filter(t => t[0] >= d365);
    $('rstats').innerHTML = RT.length ? (
      `<div><small>최근 전세</small><b class="t">${J.length ? won(J[0][1]) : '-'}</b>${J.length ? `<em>${dL(J[0][0])} · ${J[0][3]}층</em>` : ''}</div>` +
      `<div><small>전세 최고</small><b class="t">${jmax ? won(jmax[1]) : '-'}</b>${jmax ? `<em>${dL(jmax[0])}</em>` : ''}</div>` +
      `<div><small>전세가율</small><b class="k">${ja && sa ? Math.round(ja / sa * 100) + '%' : '-'}</b><em>전세÷매매</em></div>` +
      `<div><small>1년 거래</small><b class="k">${y1.length}건</b><em>전세 ${y1.filter(t => !t[2]).length} · 월세 ${y1.filter(t => t[2]).length}</em></div>`) : '';
    $('rrows').innerHTML = RT.length ? RT.slice(0, rshown).map(t => `<tr><td>${dL(t[0])}</td><td>${t[3]}층</td>` +
      (t[2] ? `<td class="p w">월 ${won(t[1])}/${t[2].toLocaleString()}</td>` : `<td class="p">${won(t[1])}</td>`) + '</tr>').join('')
      : `<tr><td colspan="3" class="none">최근 13개월 ${curL()} 전월세 거래가 없습니다</td></tr>`;
    const mb = $('rmore');
    mb.style.display = rshown < RT.length ? '' : 'none';
    mb.textContent = `더보기 (${(RT.length - rshown).toLocaleString()}건 남음)`;
    mb.onclick = () => { rshown += 20; rent(T); };
  }

  // ---- 그래프: 위 = 월평균 선, 아래 = 거래량 막대 (가로축은 실제 시간)
  function chart(T) {
    const box = $('chart'), svg = $('svg'), tip = $('tip'), rngEl = $('rng');
    const by = {};
    T.forEach(t => { const ym = ymOf(t[0]); (by[ym] = by[ym] || []).push(t[1]); });
    const M = Object.keys(by).map(Number).sort((a, b) => a - b).map(ym => ({ ym, n: by[ym].length, avg: by[ym].reduce((a, b) => a + b, 0) / by[ym].length }));
    if (!M.length) { box.classList.add('empty'); svg.innerHTML = ''; tip.style.display = rngEl.style.display = 'none'; box.dataset.msg = '1'; svg.style.display = 'none'; if (!box.querySelector('.msg')) box.insertAdjacentHTML('beforeend', '<div class="msg">매매 거래가 없습니다</div>'); return; }
    box.classList.remove('empty'); svg.style.display = ''; const msg = box.querySelector('.msg'); if (msg) msg.remove();
    const W = svg.clientWidth || 660, H = svg.clientHeight || 250;
    const P = { l: 44, r: 12, t: 40, b: 22 }, VH = 40, PB = H - P.b - VH - 10, vb = H - P.b;
    const m0 = mIdx(M[0].ym), m1 = Math.max(mIdx(M[M.length - 1].ym), m0 + 1);
    const xs = i => P.l + (W - P.l - P.r) * (mIdx(M[i].ym) - m0) / (m1 - m0);
    const xm = m => P.l + (W - P.l - P.r) * (m - m0) / (m1 - m0);
    let mn = Math.min(...M.map(m => m.avg)), mx = Math.max(...M.map(m => m.avg));
    if (mx - mn < mx * 0.1) { mn -= mx * 0.05; mx += mx * 0.05; }
    mn *= 0.97; mx *= 1.02;
    const ys = v => P.t + (PB - P.t) * (1 - (v - mn) / (mx - mn));
    const nmax = Math.max(...M.map(m => m.n)), vs = n => VH * n / nmax;
    let g = '';
    for (let k = 0; k < 4; k++) { const v = mn + (mx - mn) * k / 3; g += `<line x1="${P.l}" x2="${W - P.r}" y1="${ys(v)}" y2="${ys(v)}" stroke="#eef0f4"/><text x="${P.l - 6}" y="${ys(v) + 4}" font-size="10" text-anchor="end" fill="#8a94a3">${eok(v)}</text>`; }
    g += `<text x="${P.l - 6}" y="${vb - 2}" font-size="10" text-anchor="end" fill="#8a94a3">거래량</text><line x1="${P.l}" x2="${W - P.r}" y1="${vb}" y2="${vb}" stroke="#e3e7ee"/>`;
    const y0 = Math.floor(M[0].ym / 100), y1 = Math.floor(M[M.length - 1].ym / 100), step = Math.max(1, Math.ceil((y1 - y0 + 1) / 6));
    for (let y = y0 + (M[0].ym % 100 > 1 ? 1 : 0); y <= y1; y += step) { const x = xm(y * 12); if (x >= P.l && x <= W - P.r) g += `<line x1="${x}" x2="${x}" y1="${vb}" y2="${vb + 4}" stroke="#c9d0da"/><text x="${x}" y="${H - 6}" font-size="10" text-anchor="middle" fill="#8a94a3">${String(y).slice(2)}년</text>`; }
    const bw = Math.max(1.2, Math.min(8, (W - P.l - P.r) / (m1 - m0 + 1) * 0.7));
    const bars = M.map((m, i) => `<rect class="vb" data-i="${i}" x="${xs(i) - bw / 2}" y="${vb - vs(m.n)}" width="${bw}" height="${vs(m.n)}" rx="1" fill="#c9d2e4"/>`).join('');
    const path = M.map((m, i) => (i ? 'L' : 'M') + xs(i).toFixed(1) + ',' + ys(m.avg).toFixed(1)).join('');
    svg.innerHTML = g + '<path id="area" d=""/>' + bars + `<path d="${path}" fill="none" stroke="#2754d6" stroke-width="2" stroke-linejoin="round"/>` +
      '<line id="vl" stroke="#2754d6" stroke-dasharray="3 3" style="display:none"/><line id="vl2" stroke="#2754d6" stroke-dasharray="3 3" style="display:none"/>' +
      '<circle id="dot" r="5" fill="#2754d6" stroke="#fff" stroke-width="2" style="display:none"/><circle id="dot2" r="5" fill="#2754d6" stroke="#fff" stroke-width="2" style="display:none"/>';
    const q = id => svg.querySelector('#' + id);
    const idx = cx => { const r = svg.getBoundingClientRect(), x = cx - r.left; let bi = 0, bd = 1e9; M.forEach((m, i) => { const d = Math.abs(xs(i) - x); if (d < bd) { bd = d; bi = i; } }); return bi; };
    const mark = (i, dot, vl) => { q(dot).setAttribute('cx', xs(i)); q(dot).setAttribute('cy', ys(M[i].avg)); q(dot).style.display = ''; const l = q(vl); l.setAttribute('x1', xs(i)); l.setAttribute('x2', xs(i)); l.setAttribute('y1', P.t - 6); l.setAttribute('y2', vb); l.style.display = ''; };
    const paint = f => svg.querySelectorAll('.vb').forEach(b => b.setAttribute('fill', f(+b.dataset.i)));
    function one(i) {                                       // 그 달 평균 · 거래 건수
      q('dot2').style.display = q('vl2').style.display = 'none'; q('area').setAttribute('d', ''); rngEl.style.display = 'none';
      paint(j => j === i ? '#2c3563' : '#c9d2e4');
      mark(i, 'dot', 'vl'); const m = M[i];
      tip.innerHTML = `${String(m.ym).slice(0, 4)}년 ${+String(m.ym).slice(4)}월<b>평균 ${eok(m.avg)}</b>거래 ${m.n}건`;
      tip.style.display = 'block';
      tip.style.left = Math.max(64, Math.min(W - 60, xs(i))) + 'px'; tip.style.top = Math.max(52, ys(m.avg) + 2) + 'px';
    }
    function two(a, b) {                                    // 기간 수익금 · 수익률
      if (a > b) [a, b] = [b, a]; if (a === b) return one(a);
      tip.style.display = 'none'; mark(a, 'dot', 'vl'); mark(b, 'dot2', 'vl2');
      paint(j => j >= a && j <= b ? '#2c3563' : '#dde3ee');
      const A = M[a], B = M[b], diff = B.avg - A.avg, pct = diff / A.avg * 100, up = diff >= 0, sg = up ? '+' : '-';
      const seg = M.slice(a, b + 1).map((m, k) => `${xs(a + k)},${ys(m.avg)}`).join(' L');
      q('area').setAttribute('d', `M${xs(a)},${PB} L${seg} L${xs(b)},${PB} Z`);
      q('area').setAttribute('fill', up ? 'rgba(224,71,44,.14)' : 'rgba(39,84,214,.14)');
      rngEl.innerHTML = `${ymL(A.ym)}~${ymL(B.ym)} (${mdiff(A.ym, B.ym)})&nbsp; <b class="${up ? 'up' : 'dn'}">${sg}${(Math.abs(diff) / 10000).toFixed(2)}억 (${sg}${Math.round(Math.abs(pct))}%)</b>`;
      rngEl.style.display = 'block';
    }
    const touch = e => { const t = e.touches; if (t.length >= 2) { e.preventDefault(); two(idx(t[0].clientX), idx(t[1].clientX)); } else if (t.length === 1) one(idx(t[0].clientX)); };
    svg.ontouchstart = svg.ontouchmove = null;
    if (!svg._bound) { svg.addEventListener('touchstart', e => svg._h(e), { passive: false }); svg.addEventListener('touchmove', e => svg._h(e), { passive: false }); svg._bound = 1; }
    svg._h = touch;
    let drag = null;
    svg.onmousedown = e => { drag = idx(e.clientX); };
    svg.onmousemove = e => { if (drag !== null && e.buttons) two(drag, idx(e.clientX)); else if (!e.buttons) one(idx(e.clientX)); };
    svg.onmouseup = e => { const j = idx(e.clientX); if (drag === j) one(j); drag = null; };
    one(M.length - 1);
  }

  // ---- 거래 활발도 (매매 전체 타입)
  (function act() {
    const c3 = S.filter(t => t[0] >= d92).length, c1 = S.filter(t => t[0] >= d365).length;
    const ch = c1 ? Math.round((c3 * 4 / c1 - 1) * 100) : 0;
    const tr = !c1 ? ['', '-'] : ch >= 10 ? ['strong', '▲ 강세'] : ch >= 5 ? ['up', '▲ 증가'] : ch <= -10 ? ['weak', '▼ 약세'] : ch <= -5 ? ['down', '▼ 감소'] : ['', '보합'];
    const rate = n => D.hh ? `<div class="sub">회전율 ${(n / D.hh * 100).toFixed(2)}%</div>` : '';
    $('actb').innerHTML = `<div><small>최근 3개월</small><b style="color:#c46a1c">${c3}건</b>${rate(c3)}</div>` +
      `<div><small>최근 1년</small><b style="color:#137a6c">${c1}건</b>${rate(c1)}</div>` +
      `<div><small>추세</small>${c1 ? `<span class="badge ${tr[0]}">${tr[1]} ${ch > 0 ? '+' : ''}${ch}%</span>` : '<b>-</b>'}</div>`;
  })();

  // 네이버지도: 휴대폰은 앱에서 단지 위치에 핀 (앱이 없으면 웹 검색으로)
  const nm = document.querySelector('.nmap[data-lat]');
  if (nm && /iPhone|iPad|Android/i.test(navigator.userAgent)) nm.addEventListener('click', e => {
    e.preventDefault();
    const web = nm.href, t = Date.now();
    location.href = `nmap://place?lat=${nm.dataset.lat}&lng=${nm.dataset.lng}&name=${encodeURIComponent(nm.dataset.name)}&appname=nextdoorprice.com`;
    setTimeout(() => { if (!document.hidden && Date.now() - t < 2500) location.href = web; }, 1500);
  });

  draw();
  let rw = window.innerWidth;
  window.addEventListener('resize', () => { if (window.innerWidth !== rw) { rw = window.innerWidth; draw(); } });
})();
