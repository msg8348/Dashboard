// 옆집얼마 서비스 워커 — 홈 화면 앱 설치용 (나중에 알림 수신도 여기서)
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
