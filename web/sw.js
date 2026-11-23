// Only the public application shell is available offline. Never cache API responses or observations.
const cacheName = "campuscats-shell-v4";
const shell = ["/", "/app.js", "/ui.js", "/capture.js", "/review.js", "/album.js", "/surveys.js", "/style.css",
  "/manifest.webmanifest", "/assets/field-cat.jpg", "/assets/icon-192.png", "/assets/icon-512.png"];
self.addEventListener("install", event => {
  event.waitUntil(caches.open(cacheName).then(cache => cache.addAll(shell)));
});
self.addEventListener("activate", event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith("campuscats-shell-") && key !== cacheName).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin || url.search) return;
  if (!shell.includes(url.pathname) && !/^\/[a-z0-9_-]+\.(css|js)$/.test(url.pathname)) return;
  event.respondWith((async () => {
    const cache = await caches.open(cacheName);
    try {
      const response = await fetch(event.request);
      if (response.ok && !response.redirected) await cache.put(event.request, response.clone());
      return response;
    } catch {
      return (await cache.match(event.request)) || Response.error();
    }
  })());
});
