// v4 instala la estrategia de actualización automática. No será necesario
// cambiar este identificador para publicar cambios posteriores.
const CACHE = 'ytmp3-studio-shell-v4';
const ASSETS = ['./', './index.html', './styles.css', './app.js', './manifest.webmanifest', './icon.svg'];
self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting())));
self.addEventListener('activate', event => event.waitUntil(Promise.all([
  caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key)))),
  self.clients.claim(),
])));

// Con conexión, siempre se consulta la versión publicada antes de responder.
// Así GitHub Pages puede actualizar HTML, CSS y JavaScript sin una subida de
// versión manual de la caché. Si no hay red, se conserva el modo offline.
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET' || new URL(event.request.url).origin !== self.location.origin) return;

  event.respondWith((async () => {
    try {
      const response = await fetch(new Request(event.request, { cache: 'no-store' }));
      if (response.ok) {
        const cache = await caches.open(CACHE);
        await cache.put(event.request, response.clone());
      }
      return response;
    } catch {
      return (await caches.match(event.request)) || (event.request.mode === 'navigate' && await caches.match('./index.html')) || Response.error();
    }
  })());
});
