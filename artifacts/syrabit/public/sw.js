const CACHE_NAME = 'syrabit-v4.0-pwa';
const STATIC_ASSETS = [
  '/manifest.json',
  '/offline.html',
  '/icons/icon-72x72.png',
  '/icons/icon-96x96.png',
  '/icons/icon-128x128.png',
  '/icons/icon-144x144.png',
  '/icons/icon-152x152.png',
  '/icons/icon-192x192.png',
  '/icons/icon-384x384.png',
  '/icons/icon-512x512.png',
];

const RUNTIME_CACHE = 'syrabit-runtime-v1';
const API_CACHE = 'syrabit-api-v1';
const FONT_CACHE = 'syrabit-fonts-v1';

const MAX_RUNTIME_ENTRIES = 80;
const MAX_API_ENTRIES = 50;
const API_CACHE_TTL = 5 * 60 * 1000;

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  const keepCaches = [CACHE_NAME, RUNTIME_CACHE, API_CACHE, FONT_CACHE];
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => !keepCaches.includes(key))
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (url.origin !== self.location.origin) {
    if (url.hostname.includes('fonts.googleapis.com') || url.hostname.includes('fonts.gstatic.com')) {
      event.respondWith(fontCacheFirst(request));
      return;
    }
    return;
  }

  if (
    url.pathname.includes('/ai/chat/stream') ||
    url.pathname.includes('/ai/chat') ||
    url.pathname.startsWith('/api/cms/') ||
    url.pathname.startsWith('/api/analytics/')
  ) {
    return;
  }

  if (request.method !== 'GET') return;

  if (url.pathname.startsWith('/api/content/')) {
    event.respondWith(staleWhileRevalidate(request, API_CACHE, API_CACHE_TTL));
    return;
  }

  if (url.pathname.startsWith('/api/library') || url.pathname.startsWith('/api/subjects')) {
    event.respondWith(staleWhileRevalidate(request, API_CACHE, API_CACHE_TTL));
    return;
  }

  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(request));
    return;
  }

  const isAsset = url.pathname.match(/\.(png|jpg|jpeg|gif|svg|ico|webp|avif|woff2?|ttf|eot)$/);
  if (isAsset) {
    event.respondWith(cacheFirst(request, RUNTIME_CACHE));
    return;
  }

  const isHashed = url.pathname.match(/\/assets\/.*-[a-f0-9]{8,}\.(js|css)$/);
  if (isHashed) {
    event.respondWith(cacheFirst(request, RUNTIME_CACHE));
    return;
  }

  if (request.mode === 'navigate') {
    event.respondWith(navigationHandler(request));
    return;
  }

  event.respondWith(networkFirst(request));
});

async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, response.clone());
      trimCache(cacheName, MAX_RUNTIME_ENTRIES);
    }
    return response;
  } catch {
    return new Response('', { status: 408 });
  }
}

async function fontCacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(FONT_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    return new Response('', { status: 408 });
  }
}

async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(RUNTIME_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    return cached || new Response('', { status: 408 });
  }
}

async function staleWhileRevalidate(request, cacheName, ttl) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);

  const fetchPromise = fetch(request).then((response) => {
    if (response.ok) {
      const headers = new Headers(response.headers);
      headers.set('sw-cache-time', String(Date.now()));
      const timedResponse = new Response(response.clone().body, {
        status: response.status,
        statusText: response.statusText,
        headers,
      });
      cache.put(request, timedResponse);
      trimCache(cacheName, MAX_API_ENTRIES);
    }
    return response;
  }).catch(() => cached);

  if (cached) {
    const cacheTime = Number(cached.headers.get('sw-cache-time') || 0);
    if (cacheTime && Date.now() - cacheTime < ttl) {
      fetchPromise.catch(() => {});
      return cached;
    }
  }

  return fetchPromise;
}

async function navigationHandler(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(RUNTIME_CACHE);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    return caches.match('/offline.html');
  }
}

async function trimCache(cacheName, maxEntries) {
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  if (keys.length > maxEntries) {
    await cache.delete(keys[0]);
    trimCache(cacheName, maxEntries);
  }
}

self.addEventListener('sync', (event) => {
  if (event.tag === 'chat-sync') {
    // placeholder for offline chat sync
  }
});

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
