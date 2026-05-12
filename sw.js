const CACHE = 's2g12-v1';
const STATIC = [
  '/static/icon.svg', '/static/icon-192.png', '/static/icon-512.png', '/static/icon-180.png',
  '/static/manifest.json',
];
const API = ['/api/files', '/api/exams', '/api/announcements', '/api/recent', '/api/files/popular', '/api/ai-status'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(STATIC)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (API.some(p => url.pathname === p)) {
    e.respondWith(networkFirst(e.request));
  } else if (url.origin === location.origin || url.hostname.endsWith('.cloudinary.com')) {
    e.respondWith(cacheFirst(e.request));
  }
});

async function cacheFirst(req) {
  const hit = await caches.match(req);
  if (hit) return hit;
  try {
    const res = await fetch(req);
    if (res.ok) { const cache = await caches.open(CACHE); cache.put(req, res.clone()); }
    return res;
  } catch(e) { return new Response('Offline', {status: 503}); }
}

async function networkFirst(req) {
  try {
    const res = await fetch(req);
    if (res.ok) { const cache = await caches.open(CACHE); cache.put(req, res.clone()); }
    return res;
  } catch(e) {
    const hit = await caches.match(req);
    return hit || new Response(JSON.stringify({offline: true}), {status: 503, headers: {'Content-Type':'application/json'}});
  }
}
