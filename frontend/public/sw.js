// Minimal service worker for installability
// Cache strategy can be enhanced later; for now we just claim clients
const CACHE_NAME = 'johnify-pwa-v1';

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

// Required fetch listener (can be no-op) so some browsers treat SW as active
self.addEventListener('fetch', (event) => {
  // Pass-through for now; add caching if needed
});
