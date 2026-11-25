// Solo se cachea el cascarón de la app; /api nunca se cachea (el estado oficial está en el dataset).
const C = "consola-v1";
const SHELL = ["/", "/static/app.js", "/static/app.css", "/static/icono.svg", "/manifest.webmanifest"];
self.addEventListener("install", (e) => e.waitUntil(caches.open(C).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", (e) => e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== C).map((k) => caches.delete(k))))));
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.pathname.startsWith("/api") || u.pathname.startsWith("/oauth")) return;
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
