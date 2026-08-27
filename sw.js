const CACHE="chennai22k-v3";
const SHELL=["./","./index.html","./manifest.webmanifest","./icon.svg"];

self.addEventListener("install",event=>{
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE).then(cache=>cache.addAll(SHELL))
  );
});

self.addEventListener("activate",event=>{
  event.waitUntil(
    caches.keys().then(keys=>
      Promise.all(
        keys.filter(k=>k!==CACHE).map(k=>caches.delete(k))
      )
    ).then(()=>self.clients.claim())
  );
});

self.addEventListener("fetch",event=>{
  const url=new URL(event.request.url);

  // Never serve the gold data from the service-worker cache.
  if(url.pathname.endsWith("/data.json")){
    event.respondWith(fetch(event.request,{cache:"no-store"}).catch(()=>caches.match(event.request)));
    return;
  }

  // Network-first for the app shell, with offline fallback.
  if(event.request.mode==="navigate" || url.pathname.endsWith("/index.html")){
    event.respondWith(
      fetch(event.request,{cache:"no-store"})
        .then(response=>{
          const copy=response.clone();
          caches.open(CACHE).then(c=>c.put("./index.html",copy));
          return response;
        })
        .catch(()=>caches.match("./index.html"))
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then(cached=>cached||fetch(event.request))
  );
});
