/* ================================================================
   sw.js — Service Worker for Crop Sathi PWA
   - Cache-first for static assets
   - Network-first for API calls with offline queue
   - Background sync with /sync endpoint
   ================================================================ */

const CACHE_NAME = "crop-sathi-v3";
const API_HOST = "127.0.0.1:8000";

const STATIC_ASSETS = [
  "./",
  "./index.html",
  "./css/style.css",
  "./js/icons.js",
  "./js/db.js",
  "./js/app.js",
  "./manifest.json",
  "./assets/images/hero-farming.jpg",
];

// ── Install: pre-cache static assets ──
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())
  );
});

// ── Activate: clean old caches ──
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

// ── Fetch strategy ──
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // API calls → network-first
  if (url.host === API_HOST) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          // Cache successful GET API responses for offline
          if (event.request.method === "GET" && response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // Static assets → cache-first
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        // Cache new requests (same-origin only)
        if (response.ok && url.origin === self.location.origin) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        }
        return response;
      });
    })
  );
});

// ── Background Sync ──
self.addEventListener("sync", (event) => {
  if (event.tag === "crop-sathi-sync") {
    event.waitUntil(processSyncQueue());
  }
});

async function processSyncQueue() {
  try {
    // Open IndexedDB to get queued actions
    const db = await openDB();
    const tx = db.transaction("syncQueue", "readonly");
    const store = tx.objectStore("syncQueue");
    const request = store.getAll();

    const actions = await new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });

    if (!actions.length) return;

    // Send batch to /sync endpoint
    const response = await fetch(`http://${API_HOST}/sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actions }),
    });

    if (response.ok) {
      // Parse the response before iterating clients
      const syncResults = await response.json();

      // Clear the queue on success
      const clearTx = db.transaction("syncQueue", "readwrite");
      clearTx.objectStore("syncQueue").clear();
      await new Promise((resolve) => { clearTx.oncomplete = resolve; });

      // Notify the client
      const clients = await self.clients.matchAll();
      clients.forEach((client) => {
        client.postMessage({ type: "SYNC_COMPLETE", results: syncResults });
      });
    }
  } catch (err) {
    console.warn("Sync failed, will retry:", err);
  }
}

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open("CropSathiDB", 1);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains("syncQueue")) {
        db.createObjectStore("syncQueue", { keyPath: "id", autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
