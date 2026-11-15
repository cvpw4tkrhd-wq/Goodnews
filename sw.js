// Ljusglimtar – service worker.
// Appskalet cachas, news.json hämtas alltid från nätet först och faller
// tillbaka på senast sparade version när du är offline.
const CACHE = "ljusglimtar-v2";
const SHELL = ["./", "index.html", "manifest.webmanifest", "icon-180.png", "icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return; // bilder m.m. går direkt
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          const key = url.pathname.endsWith("news.json") ? "news.json" : e.request;
          caches.open(CACHE).then((c) => c.put(key, copy));
        }
        return res;
      })
      .catch(() =>
        caches.match(url.pathname.endsWith("news.json") ? "news.json" : e.request)
          .then((hit) => hit || caches.match("index.html"))
      )
  );
});
