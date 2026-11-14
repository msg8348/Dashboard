// 분양권 페이지: 타입별 분양가·프리미엄 표 · 평형 선택 · 월평균 그래프(분양가 점선) · 거래표
(function () {
  const D = JSON.parse(document.getElementById('pdata').textContent);
  const TY = D.ty, T = D.t, SCAN = new Set(D.scan || []);                 // TY: [약식표기, 세대수, 최고분양가]  T: [계약일, 금액, 층, 약식표기, 분양가, 상세여부]
  const $ = id => document.getElementById(id);
  const won = v => { const e = Math.floor(v / 10000), r = v % 10000; return (e ? e + '억' : '') + (r ? (e ? ' ' : '') + r.toLocaleString() : '') || '0'; };
  const pm = v => (v >= 0 ? '+' : '-') + (Math.abs(v) >= 10000 ? (Math.abs(v) / 10000).toFixed(2) + '억' : Math.abs(v).toLocaleString() + '만');
  const eok = v => (Math.round(v / 1000) / 10).toFixed(1) + '억';
  const eok2 = v => (v / 10000).toFixed(2).replace(/0$/, '') + '억';
  const dL = d => { const s = String(d); return `${s.slice(2, 4)}.${s.slice(4, 6)}.${s.slice(6, 8)}`; };
  const avg = a => a.length ? a.reduce((s, x) => s + x, 0) / a.length : 0;
  const r100 = v => Math.round(v / 100) * 100;
  const mIdx = ym => Math.floor(ym / 100) * 12 + (ym % 100) - 1;
  const ago = days => { const t = new Date(+TODAY.slice(0, 4), +TODAY.slice(4, 6) - 1, +TODAY.slice(6, 8) - days); return t.getFullYear() * 10000 + (t.getMonth() + 1) * 100 + t.getDate(); };
  const d92 = ago(92);
  const grp = l => l.replace(/[A-Za-z]+$/, '');

  // 타입별 분양가·프리미엄 표
  $('pcap').textContent = SCAN.size === TY.length ? '층별 분양가 기준' : SCAN.size ? '층별 · 일부 최고 분양가' : '최고 분양가 기준';
  $('ptab').innerHTML = TY.map(([l, n, top]) => {
    const r = T.filter(t => t[3] === l && t[0] >= d92), m = avg(r.map(t => t[1])), p = avg(r.map(t => t[1] - t[4]));
    const rg = D.rng[l];
    const sp = rg ? (rg[0] === rg[1] ? eok2(rg[0]) : `${eok2(rg[0])}~${eok2(rg[1])}`) : (top ? '최고 ' + eok2(top) : '-');
    return `<tr><td><b>${l}</b></td><td>${n.toLocaleString()}</td><td>${sp}</td><td>${m ? won(r100(m)) : '-'}</td><td class="pm ${p < 0 ? 'n' : ''}">${r.length ? pm(r100(p)) : '-'}</td></tr>`;
  }).join('');
  $('pnote').textContent = SCAN.size
    ? '프리미엄 = 거래가 − 그 타입·층의 분양가(모집공고문). 분양권 거래에는 동이 없어 같은 층 구간 분양가의 평균으로 계산해요.'
    : '이 단지는 모집공고문의 층별 분양가를 읽지 못해, 프리미엄을 그 타입 최고 분양가(청약홈) 대비로 계산해요. 저층 거래는 실제보다 작게 보일 수 있어요.';

  const G = [...new Set(TY.map(t => grp(t[0])))].filter(g => T.some(t => grp(t[3]) === g));
  let cur = G.includes('84') ? '84' : G.slice().sort((a, b) => T.filter(t => grp(t[3]) === b).length - T.filter(t => grp(t[3]) === a).length)[0];
  let shown = 10;

  function draw() {
    $('types').innerHTML = G.length > 1 ? G.map(g => `<button type="button" class="${g === cur ? 'on' : ''}" data-k="${g}">${g}㎡</button>`).join('') : '';
    $('types').querySelectorAll('button').forEach(b => b.onclick = () => { cur = b.dataset.k; shown = 10; draw(); });
    const R = T.filter(t => grp(t[3]) === cur), sup = TY.filter(t => grp(t[0]) === cur).reduce((s, t) => s + t[1], 0);
    if (!R.length) return;
    const last = R[0], max = R.reduce((a, b) => b[1] > a[1] ? b : a), rec = R.filter(t => t[0] >= d92), ap = avg(rec.map(t => t[1] - t[4]));
    $('stats').innerHTML = `<div><small>최근 거래</small><b>${won(last[1])}</b><em>${dL(last[0])} · ${last[2]}층 · ${last[3]}</em></div>` +
      `<div><small>최고가</small><b class="r">${won(max[1])}</b><em>${dL(max[0])} · ${max[2]}층 · ${max[3]}</em></div>` +
      `<div><small>분양 이후 거래</small><b class="k">${R.length.toLocaleString()}건</b><em>${cur}타입 분양 ${sup.toLocaleString()}세대 중 <b class="pct">${sup ? Math.round(R.length / sup * 100) : 0}%</b></em></div>` +
      `<div><small>평균 프리미엄</small><b class="p ${ap < 0 ? 'n' : ''}">${rec.length ? pm(r100(ap)) : '-'}</b><em>최근 3개월 · ${R.every(t => t[5]) ? '층별 분양가 대비' : '최고 분양가 대비 포함'}</em></div>`;
    $('miss').hidden = TY.filter(t => grp(t[0]) === cur).every(t => SCAN.has(t[0]));
    chart(R);
    $('rows').innerHTML = R.slice(0, shown).map(t => `<tr><td>${dL(t[0])}</td><td class="p">${won(t[1])}</td><td>${t[2]}층</td><td class="ty">${t[3]}</td><td class="p pm ${t[1] < t[4] ? 'n' : ''}">${pm(t[1] - t[4])}</td></tr>`).join('');
    const mb = $('more');
    mb.style.display = shown < R.length ? '' : 'none';
    mb.textContent = `더보기 (${(R.length - shown).toLocaleString()}건 남음)`;
    mb.onclick = () => { shown += 20; draw(); };
  }

  function chart(R) {
    const svg = $('svg'), tip = $('tip');
    const by = {};
    R.forEach(t => { const ym = Math.floor(t[0] / 100); (by[ym] = by[ym] || []).push(t[1]); });
    const M = Object.keys(by).map(Number).sort((a, b) => a - b).map(ym => ({ ym, n: by[ym].length, avg: avg(by[ym]) }));
    const sp = avg(R.map(t => t[4]));
    const W = svg.clientWidth || 660, H = svg.clientHeight || 250, P = { l: 44, r: 12, t: 30, b: 22 }, VH = 40, PB = H - P.b - VH - 10, vb = H - P.b;
    const m0 = mIdx(M[0].ym), m1 = Math.max(mIdx(M[M.length - 1].ym), m0 + 1);
    const pad = M.length === 1 ? 0.5 : 0;
    const xs = i => P.l + (W - P.l - P.r) * (M.length === 1 ? 0.5 : (mIdx(M[i].ym) - m0) / (m1 - m0));
    let mn = Math.min(sp, ...M.map(m => m.avg)), mx = Math.max(sp, ...M.map(m => m.avg));
    if (mx - mn < mx * 0.08) { mn -= mx * 0.04; mx += mx * 0.04; }
    mn *= 0.98; mx *= 1.02;
    const ys = v => P.t + (PB - P.t) * (1 - (v - mn) / (mx - mn));
    const nmax = Math.max(...M.map(m => m.n));
    let g = '';
    for (let k = 0; k < 4; k++) { const v = mn + (mx - mn) * k / 3; g += `<line x1="${P.l}" x2="${W - P.r}" y1="${ys(v)}" y2="${ys(v)}" stroke="#eef0f4"/><text x="${P.l - 6}" y="${ys(v) + 4}" font-size="10" text-anchor="end" fill="#8a94a3">${eok(v)}</text>`; }
    g += `<path d="M${xs(0)},${ys(sp)} ${M.map((m, i) => `L${xs(i)},${ys(m.avg)}`).join(' ')} L${xs(M.length - 1)},${ys(sp)} Z" fill="rgba(224,71,44,.12)"/>`;
    g += `<line x1="${P.l}" x2="${W - P.r}" y1="${ys(sp)}" y2="${ys(sp)}" stroke="#c2185b" stroke-dasharray="5 4" stroke-width="1.6"/><text x="${W - P.r - 4}" y="${ys(sp) + 14}" font-size="10.5" font-weight="700" text-anchor="end" fill="#c2185b">분양가 ${eok(sp)}</text>`;
    const bw = Math.max(3, Math.min(14, (W - P.l - P.r) / (m1 - m0 + 1) * 0.6));
    g += M.map((m, i) => `<rect class="vb" data-i="${i}" x="${xs(i) - bw / 2}" y="${vb - VH * m.n / nmax}" width="${bw}" height="${VH * m.n / nmax}" rx="1.5" fill="#c9d2e4"/>`).join('');
    const step = Math.max(1, Math.ceil(M.length / 7));
    g += M.map((m, i) => i % step ? '' : `<text x="${xs(i)}" y="${H - 6}" font-size="10" text-anchor="middle" fill="#8a94a3">${String(m.ym).slice(2, 4)}.${String(m.ym).slice(4)}</text>`).join('');
    g += `<text x="${P.l - 6}" y="${vb - 2}" font-size="10" text-anchor="end" fill="#8a94a3">거래량</text><line x1="${P.l}" x2="${W - P.r}" y1="${vb}" y2="${vb}" stroke="#e3e7ee"/>`;
    g += `<path d="${M.map((m, i) => (i ? 'L' : 'M') + xs(i) + ',' + ys(m.avg)).join('')}" fill="none" stroke="#2754d6" stroke-width="2"/>` + M.map((m, i) => `<circle cx="${xs(i)}" cy="${ys(m.avg)}" r="2.6" fill="#2754d6"/>`).join('');
    g += '<circle id="dot" r="5" fill="#2754d6" stroke="#fff" stroke-width="2" style="display:none"/>';
    svg.innerHTML = g;
    const dot = svg.querySelector('#dot');
    const idx = cx => { const r = svg.getBoundingClientRect(), x = cx - r.left; let bi = 0, bd = 1e9; M.forEach((m, i) => { const d = Math.abs(xs(i) - x); if (d < bd) { bd = d; bi = i; } }); return bi; };
    function one(i) {
      const m = M[i];
      dot.setAttribute('cx', xs(i)); dot.setAttribute('cy', ys(m.avg)); dot.style.display = '';
      svg.querySelectorAll('.vb').forEach(b => b.setAttribute('fill', +b.dataset.i === i ? '#2c3563' : '#c9d2e4'));
      tip.innerHTML = `${String(m.ym).slice(0, 4)}년 ${+String(m.ym).slice(4)}월<b>평균 ${eok(m.avg)}</b>거래 ${m.n}건 · 프리미엄 ${pm(r100(m.avg - sp))}`;
      tip.style.display = 'block';
      tip.style.left = Math.max(80, Math.min(W - 80, xs(i))) + 'px'; tip.style.top = Math.max(52, ys(m.avg) + 2) + 'px';
    }
    svg.onmousemove = e => one(idx(e.clientX));
    svg.ontouchstart = svg.ontouchmove = e => { if (e.touches.length === 1) one(idx(e.touches[0].clientX)); };
    one(M.length - 1);
  }

  (function act() {   // 거래 활발도: 최근 3개월·1년 거래, 세대수 대비 회전율, 추세
    const d365 = ago(365), c3 = T.filter(t => t[0] >= d92).length, c1 = T.filter(t => t[0] >= d365).length;
    const ch = c1 ? Math.round((c3 * 4 / c1 - 1) * 100) : 0;
    const tr = !c1 ? ['', '-'] : ch >= 10 ? ['strong', '▲ 강세'] : ch >= 5 ? ['up', '▲ 증가'] : ch <= -10 ? ['weak', '▼ 약세'] : ch <= -5 ? ['down', '▼ 감소'] : ['', '보합'];
    const rate = n => D.hh ? `<div class="sub">회전율 ${(n / D.hh * 100).toFixed(2)}%</div>` : '';
    $('actb').innerHTML = `<div><small>최근 3개월</small><b style="color:#c46a1c">${c3}건</b>${rate(c3)}</div>` +
      `<div><small>최근 1년</small><b style="color:#137a6c">${c1}건</b>${rate(c1)}</div>` +
      `<div><small>추세</small>${c1 ? `<span class="badge ${tr[0]}">${tr[1]} ${ch > 0 ? '+' : ''}${ch}%</span>` : '<b>-</b>'}</div>`;
  })();
  const nm = document.querySelector('.nmap[data-lat]');   // 네이버지도 앱: 단지 위치 핀
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
