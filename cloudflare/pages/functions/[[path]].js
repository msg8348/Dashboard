// 단지·분양권 페이지(/{시도}/apt/*, /{시도}/pre/*) — R2 의 pages/ 에서 꺼내 날짜 자리표시를 채워 보여줌.
// 어떤 주소가 여기로 오는지는 cfsite/_routes.json 이 정함 (나머지는 정적 파일).
let TODAY = '', TODAY_AT = 0;

async function today(ctx) {
  if (TODAY && Date.now() - TODAY_AT < 300000) return TODAY;   // 5분마다 다시 읽음
  try {
    const r = await ctx.env.ASSETS.fetch(new URL('/today.txt', ctx.request.url));
    if (r.ok) { TODAY = (await r.text()).trim(); TODAY_AT = Date.now(); }
  } catch (e) {}
  return TODAY;
}

export async function onRequestGet(ctx) {
  const url = new URL(ctx.request.url);
  let path = decodeURIComponent(url.pathname);
  if (!path.endsWith('.html')) path += '.html';
  const obj = await ctx.env.SITE.get('pages' + path);
  if (!obj) return new Response('페이지를 찾을 수 없어요', { status: 404, headers: { 'content-type': 'text/plain; charset=utf-8' } });
  const t = await today(ctx);
  let html = await obj.text();
  if (t) html = html.replaceAll('__TODAY__', t).replaceAll('__TODAY_DOT__', `${t.slice(2, 4)}.${t.slice(4, 6)}.${t.slice(6, 8)}`);
  return new Response(html, { headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'public, max-age=300' } });
}
