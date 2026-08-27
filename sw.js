const CACHE="chennai22k-v2";
self.addEventListener("install",e=>{
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE).then(c=>c.addAll([
      "./",
      "./index.html",
      "./manifest.webmanifest",
      "./icon.svg",
      "./data.json"
    ]))
  );
});

self.addEventListener("activate",e=>{
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k=>k!==CACHE).map(k=>caches.delete(k))
      )
    ).then(()=>self.clients.claim())
  );
});
