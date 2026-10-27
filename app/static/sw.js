/* EftiSocial — service worker PWA.
   Cache statique uniquement (réseau d'abord pour les pages : données privées). */
var CACHE = "eftisocial-v1";
var STATICS = [
  "/static/css/app.css",
  "/static/js/swipe.js",
  "/static/js/decouverte.js",
  "/static/js/membre.js",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png"
];

self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(STATICS); }));
  self.skipWaiting();
});

self.addEventListener("activate", function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        if (k !== CACHE) return caches.delete(k);
      }));
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", function (e) {
  var url = new URL(e.request.url);
  // Uniquement GET + même origine + /static : cache-first
  if (e.request.method === "GET" &&
      url.origin === location.origin &&
      url.pathname.indexOf("/static/") === 0) {
    e.respondWith(
      caches.match(e.request).then(function (hit) {
        return hit || fetch(e.request);
      })
    );
    return;
  }
  // Tout le reste : réseau d'abord (données sensibles, jamais en cache)
  e.respondWith(fetch(e.request));
});
