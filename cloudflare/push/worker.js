// 옆집얼마 알림 서버 (Cloudflare Worker)
// - 사이트의 '알림 켜기' → POST /sub 로 기기별 구독·선택(관심단지, 아침 요약 지역)을 KV 에 저장
// - 5분마다(cron) 사이트의 push.json(그날 알림 재료)을 읽어
//     ① 새 공개일이면: 관심단지에 새 거래가 있는 기기에 '관심단지 실거래' 알림
//     ② 한국시간 07시 이후 하루 한 번: 아침 요약을 켠 기기에 관심지역 요약 알림 (누르면 지역 페이지)
//   기기가 많으면 한 번에 BATCH 개씩 나눠 보내고 다음 실행에서 이어 보냄.
// - 알림 서명 키(VAPID)는 처음 요청 때 만들어 KV 에 보관 (밖으로 나가는 건 공개키뿐)
// 배포: .github/workflows/Push.yml (wrangler)

const SITE = 'https://nextdoorprice.com';
const ORIGINS = [SITE, 'https://www.nextdoorprice.com', 'http://localhost:8765'];
const BATCH = 15;            // 한 번 실행에 보내는 기기 수 (무료 요금제 CPU 한도 고려)
const SUMMARY_HOUR = 7;      // 한국시간 아침 요약 시각

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    const origin = req.headers.get('Origin') || '';
    const cors = {
      'Access-Control-Allow-Origin': ORIGINS.includes(origin) ? origin : SITE,
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
      'Vary': 'Origin',
    };
    const json = (o, status = 200) => new Response(JSON.stringify(o), { status, headers: { ...cors, 'Content-Type': 'application/json' } });
    if (req.method === 'OPTIONS') return new Response(null, { headers: cors });
    try {
      if (url.pathname === '/vapid') return json({ key: (await vapid(env)).pub });
      if (url.pathname === '/sub' && req.method === 'POST') {
        const b = await req.json();
        const s = b && b.sub;
        if (!s || typeof s.endpoint !== 'string' || !/^https:\/\//.test(s.endpoint) || !s.keys || !s.keys.p256dh || !s.keys.auth) return json({ ok: false, error: 'bad subscription' }, 400);
        const rec = {
          sub: { endpoint: s.endpoint, keys: { p256dh: String(s.keys.p256dh), auth: String(s.keys.auth) } },
          fav: Array.isArray(b.fav) ? b.fav.filter(p => typeof p === 'string' && p.length < 120).slice(0, 200) : [],
          favOn: !!b.favOn,
          daily: !!b.daily,
          region: typeof b.region === 'string' ? b.region.slice(0, 120) : '',
          rname: typeof b.rname === 'string' ? b.rname.slice(0, 40) : '',
          at: Date.now(),
        };
        if (!rec.favOn && !rec.daily) { await env.SUBS.delete(await subKey(s.endpoint)); return json({ ok: true, removed: true }); }
        await env.SUBS.put(await subKey(s.endpoint), JSON.stringify(rec));
        return json({ ok: true });
      }
      if (url.pathname === '/unsub' && req.method === 'POST') {
        const b = await req.json();
        if (b && typeof b.endpoint === 'string') await env.SUBS.delete(await subKey(b.endpoint));
        return json({ ok: true });
      }
      if (url.pathname === '/kick') {   // 매일 갱신이 끝나면 GitHub Actions 가 호출 → 바로 확인 (중복 발송은 날짜로 막음)
        ctx.waitUntil(run(env));
        return json({ ok: true });
      }
      return new Response('옆집얼마 알림 서버', { headers: cors });
    } catch (e) {
      return json({ ok: false, error: String(e && e.message || e) }, 500);
    }
  },
  async scheduled(event, env, ctx) {
    ctx.waitUntil(run(env));
  },
};

// ───────── 발송 작업 ─────────
async function run(env) {
  const st = JSON.parse(await env.SUBS.get('_state') || '{}');
  let data;
  try {
    const r = await fetch(`${SITE}/push.json?t=${Date.now()}`, { cf: { cacheTtl: 0 } });
    if (!r.ok) return;
    data = await r.json();
  } catch (e) { return; }
  const today = kstDate();
  if (!st.job) {
    if (data.new && data.date && data.date > (st.favDate || '')) st.job = { type: 'fav', date: data.date, cursor: null, sent: 0 };
    else if (kstHour() >= SUMMARY_HOUR && today > (st.sumDate || '')) st.job = { type: 'sum', date: today, cursor: null, sent: 0 };
    else return;
  }
  const job = st.job;
  const list = await env.SUBS.list({ prefix: 's:', cursor: job.cursor || undefined, limit: BATCH });
  const keys = await vapid(env);
  for (const k of list.keys) {
    const rec = JSON.parse(await env.SUBS.get(k.name) || 'null');
    if (!rec) continue;
    const msg = job.type === 'fav' ? favMsg(rec, data) : sumMsg(rec, data);
    if (!msg) continue;
    const res = await sendPush(rec.sub, msg, keys).catch(() => null);
    if (res && (res.status === 404 || res.status === 410)) await env.SUBS.delete(k.name);   // 알림을 끄거나 앱을 지운 기기
    else if (res && res.ok) job.sent++;
  }
  if (list.list_complete) {
    if (job.type === 'fav') st.favDate = job.date; else st.sumDate = job.date;
    st.last = { type: job.type, date: job.date, sent: job.sent, at: Date.now() };
    st.job = null;
  } else job.cursor = list.cursor;
  await save(env, st);
}
const save = (env, st) => env.SUBS.put('_state', JSON.stringify(st));

function favMsg(rec, data) {
  if (!rec.favOn || !rec.fav || !rec.fav.length) return null;
  const hit = rec.fav.filter(p => data.apts && data.apts[p]);
  if (!hit.length) return null;
  const a = data.apts[hit[0]];
  const more = hit.length > 1 ? ` 외 ${hit.length - 1}곳` : '';
  return {
    title: `관심단지 새 실거래 · ${a.n}${more}`,
    body: a.t.slice(0, 3).join('\n'),
    url: hit.length > 1 ? 'fav.html' : hit[0],
    tag: 'fav-' + data.date,
  };
}
function sumMsg(rec, data) {
  if (!rec.daily || !rec.region) return null;
  const g = data.regions && data.regions[rec.region];
  const d = data.date || '';
  const dl = d ? `${d.slice(2, 4)}.${d.slice(4, 6)}.${d.slice(6)}` : '';
  const name = (g && g.n) || rec.rname || '관심지역';
  const body = g
    ? `신규 매매 ${g.c.toLocaleString()}건 · 신고가 ${g.h}건${g.r != null ? ` · 전월세 ${g.r.toLocaleString()}건` : ''}${data.new ? '' : ' (새 공개 없음)'}`
    : '오늘의 실거래를 확인해 보세요';
  return { title: `${name} 아침 요약 · ${dl} 기준`, body, url: rec.region, tag: 'sum' };
}

const kstNow = () => new Date(Date.now() + 9 * 3600e3);
const kstHour = () => kstNow().getUTCHours();
const kstDate = () => kstNow().toISOString().slice(0, 10).replace(/-/g, '');

async function subKey(endpoint) {
  const h = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(endpoint));
  return 's:' + b64u(new Uint8Array(h)).slice(0, 32);
}

// ───────── Web Push (RFC 8291 aes128gcm + RFC 8292 VAPID) ─────────
const enc = new TextEncoder();
function b64u(buf) {
  let s = '';
  for (const b of new Uint8Array(buf)) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function unb64u(s) {
  s = s.replace(/-/g, '+').replace(/_/g, '/');
  const bin = atob(s + '='.repeat((4 - s.length % 4) % 4));
  return Uint8Array.from(bin, c => c.charCodeAt(0));
}
const cat = (...a) => { const o = new Uint8Array(a.reduce((n, x) => n + x.length, 0)); let i = 0; for (const x of a) { o.set(x, i); i += x.length; } return o; };

async function vapid(env) {
  let v = JSON.parse(await env.SUBS.get('_vapid') || 'null');
  if (!v) {
    const kp = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign', 'verify']);
    v = { jwk: await crypto.subtle.exportKey('jwk', kp.privateKey), pub: b64u(await crypto.subtle.exportKey('raw', kp.publicKey)) };
    await env.SUBS.put('_vapid', JSON.stringify(v));
  }
  if (!v.key) v.key = await crypto.subtle.importKey('jwk', v.jwk, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign']);
  return v;
}
async function vapidJWT(aud, v) {
  const head = b64u(enc.encode(JSON.stringify({ typ: 'JWT', alg: 'ES256' })));
  const body = b64u(enc.encode(JSON.stringify({ aud, exp: Math.floor(Date.now() / 1000) + 12 * 3600, sub: SITE })));
  const sig = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, v.key, enc.encode(`${head}.${body}`));
  return `${head}.${body}.${b64u(sig)}`;
}
async function hkdf(salt, ikm, info, len) {
  const k = await crypto.subtle.importKey('raw', ikm, 'HKDF', false, ['deriveBits']);
  return new Uint8Array(await crypto.subtle.deriveBits({ name: 'HKDF', hash: 'SHA-256', salt, info }, k, len * 8));
}
export async function encryptPayload(sub, payload) {
  const uaPub = unb64u(sub.keys.p256dh), auth = unb64u(sub.keys.auth);
  const as = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
  const asPub = new Uint8Array(await crypto.subtle.exportKey('raw', as.publicKey));
  const uaKey = await crypto.subtle.importKey('raw', uaPub, { name: 'ECDH', namedCurve: 'P-256' }, false, []);
  const shared = new Uint8Array(await crypto.subtle.deriveBits({ name: 'ECDH', public: uaKey }, as.privateKey, 256));
  const ikm = await hkdf(auth, shared, cat(enc.encode('WebPush: info\0'), uaPub, asPub), 32);
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const cek = await hkdf(salt, ikm, enc.encode('Content-Encoding: aes128gcm\0'), 16);
  const nonce = await hkdf(salt, ikm, enc.encode('Content-Encoding: nonce\0'), 12);
  const key = await crypto.subtle.importKey('raw', cek, 'AES-GCM', false, ['encrypt']);
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv: nonce }, key, cat(enc.encode(payload), new Uint8Array([2]))));
  const rs = new Uint8Array([0, 0, 16, 0]);   // 4096
  return cat(salt, rs, new Uint8Array([asPub.length]), asPub, ct);
}
export async function sendPush(sub, msg, v) {
  const aud = new URL(sub.endpoint).origin;
  const body = await encryptPayload(sub, JSON.stringify(msg));
  return fetch(sub.endpoint, {
    method: 'POST',
    headers: {
      TTL: '86400',
      Urgency: 'normal',
      'Content-Encoding': 'aes128gcm',
      'Content-Type': 'application/octet-stream',
      Authorization: `vapid t=${await vapidJWT(aud, v)}, k=${v.pub}`,
    },
    body,
  });
}
