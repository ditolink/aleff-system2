const CACHE_NAME = 'aleff-public-shell-v1';
const SHELL_URLS = [
  '/',
  '/manifest.webmanifest',
  '/assets/pwa-icon.svg',
  '/assets/pwa-icon-192.png',
  '/assets/pwa-icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_URLS)),
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith('aleff-public-shell-') && key !== CACHE_NAME)
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);

  if (
    request.method !== 'GET' ||
    url.origin !== self.location.origin ||
    url.pathname.startsWith('/api/') ||
    url.pathname.startsWith('/_vercel/')
  ) {
    return;
  }

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(async () => {
        if (url.pathname !== '/' && url.pathname !== '/index.html') throw new Error('Offline');
        const cachedHome = await caches.match('/');
        if (cachedHome) return cachedHome;
        throw new Error('Offline');
      }),
    );
    return;
  }

  const isPublicAsset =
    ['script', 'style', 'font'].includes(request.destination) ||
    url.pathname.startsWith('/assets/');

  if (!isPublicAsset) return;

  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
        }
        return response;
      });
      return cached || network;
    }),
  );
});