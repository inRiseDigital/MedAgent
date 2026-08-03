/*
 * MedAgent service worker — foundational PWA (installable + offline fallback).
 * Deliberately minimal and dev-safe: it only intercepts NAVIGATIONS
 * (network-first, falling back to /offline). It does NOT cache app chunks or
 * API responses, so Fast Refresh and fresh clinical data are never served stale.
 * Fuller offline caching of the read-only record is a follow-up.
 */
const CACHE = "medagent-shell-v1";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.add("/offline")).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.map((k) => (k === CACHE ? null : caches.delete(k))))).then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET" || req.mode !== "navigate") return;
  event.respondWith(fetch(req).catch(() => caches.match("/offline")));
});
