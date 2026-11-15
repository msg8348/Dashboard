// 옆집얼마 서비스 워커 — 홈 화면 앱 설치 · 알림 수신
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
// 서버에서 보내는 알림 {title, body, url}
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = { body: e.data && e.data.text() }; }
  e.waitUntil(self.registration.showNotification(d.title || '옆집얼마', {
    body: d.body || '', icon: 'icon-192.png', badge: 'favicon-48.png', tag: d.tag, data: { url: d.url || './' } }));
});
// 알림을 누르면 연결 페이지 (관심단지 · 관심지역 요약)
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = new URL((e.notification.data && e.notification.data.url) || './', self.registration.scope).href;
  e.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(ws => {
    for (const w of ws) if (w.url === url && 'focus' in w) return w.focus();
    return clients.openWindow(url);
  }));
});
