const CACHE_VERSION = '8';
const STATIC_CACHE = 'syrabit-static-v' + CACHE_VERSION;
const RUNTIME_CACHE = 'syrabit-runtime-v' + CACHE_VERSION;

const PRECACHE_URLS = [
  '/offline.html',
  '/manifest.json',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) =>
      cache.addAll(PRECACHE_URLS).then(() =>
        fetch(new URL('precache-manifest.json', self.registration.scope).href)
          .then((res) => res.ok ? res.json() : [])
          .then((urls) => Promise.allSettled(
            urls.map((u) => cache.add(new Request(new URL(u, self.registration.scope).href)))
          ))
          .catch(() => {})
      )
    )
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  const keep = new Set([STATIC_CACHE, RUNTIME_CACHE]);
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => !keep.has(k)).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  if (url.origin !== self.location.origin) {
    if (url.hostname.includes('fonts.googleapis.com') || url.hostname.includes('fonts.gstatic.com')) {
      event.respondWith(cacheFirst(request));
      return;
    }
    return;
  }

  if (url.pathname.startsWith('/api/')) {
    return;
  }

  if (request.mode === 'navigate') {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }

  if (isHashedAsset(url.pathname)) {
    event.respondWith(cacheFirst(request));
    return;
  }

  if (url.pathname.match(/\.(png|jpg|jpeg|gif|svg|ico|webp|avif|woff2?|ttf|eot)$/)) {
    event.respondWith(cacheFirst(request));
    return;
  }

  event.respondWith(staleWhileRevalidate(request));
});

function isHashedAsset(pathname) {
  return /\/assets\/[^/]+-[A-Za-z0-9_-]{8,}\.(js|css)$/.test(pathname);
}

async function staleWhileRevalidate(request) {
  const cached = await caches.match(request);
  const fetchPromise = fetch(request).then((response) => {
    if (response.ok) {
      const cache_promise = caches.open(RUNTIME_CACHE);
      cache_promise.then((cache) => cache.put(request, response.clone()));
    }
    return response;
  }).catch(() => null);

  if (cached) {
    fetchPromise.catch(() => {});
    return cached;
  }

  const networkResponse = await fetchPromise;
  if (networkResponse) return networkResponse;

  if (request.mode === 'navigate') {
    return caches.match('/offline.html');
  }
  return new Response('', { status: 408 });
}

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(RUNTIME_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    return new Response('', { status: 408 });
  }
}

self.addEventListener('push', (event) => {
  if (!event.data) return;
  const data = event.data.json();
  event.waitUntil(
    self.registration.showNotification(data.title || 'Syrabit.ai', {
      body: data.body || 'New notification',
      icon: '/icons/icon-192x192.png',
      badge: '/icons/icon-72x72.png',
      data: { url: data.url || '/' },
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    clients.openWindow(event.notification.data.url || '/')
  );
});

self.addEventListener('message', (event) => {
  if (event.data === 'skipWaiting') {
    self.skipWaiting();
  }
});
