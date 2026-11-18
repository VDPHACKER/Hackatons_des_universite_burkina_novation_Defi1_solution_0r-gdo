// Service worker : app shell + couches du pack en cache (hors ligne). Les appels /api sont geres par l'application (IndexedDB).
const V = 'oregdo-v41';
const VM = 'oregdo-masquage-v1';   // moteurs et modèles de masquage (≈ 45 Mo) : mis en cache à la première photo, jamais revérifiés
const FOND = ['routes_principales', 'communes', 'lieux', 'reperes', 'verts', 'decharges_osm'].map((n) => `data/pack/fond/${n}.geojson`)
  .concat(['OpenSans-Regular', 'OpenSans-Bold'].flatMap((f) => ['0-255', '256-511'].map((r) => `vendor/fonts/${f}/${r}.pbf`)));
const SHELL = ['./', 'index.html', 'manifest.webmanifest', 'css/polices.css', 'css/app.css', 'css/design.css', 'icons/logo.png', 'icons/logo-entete.png', 'vendor/polices/source-sans-3-latin-wght-normal.woff2', 'vendor/polices/source-sans-3-latin-ext-wght-normal.woff2', 'vendor/polices/source-sans-3-vietnamese-wght-normal.woff2', 'vendor/polices/bricolage-grotesque-latin-wght-normal.woff2', 'vendor/polices/bricolage-grotesque-latin-ext-wght-normal.woff2', 'js/icones.js', 'js/notifications.js', 'js/fidelite.js', 'js/sousnav.js', 'vendor/polices/bricolage-grotesque-vietnamese-wght-normal.woff2', 'js/views/tableau.js', 'js/views/parametres.js', 'js/app.js', 'js/api.js', 'js/db.js', 'js/util.js', 'js/sync.js', 'js/map.js', 'js/charts.js', 'js/kpi.js', 'js/exif.js', 'js/masquage.js', 'js/i18n.js', 'js/commune.js', 'data/i18n/dyu.json', 'data/i18n/mos.json', 'js/session.js', 'js/acces.js',
  'js/views/carte.js', 'js/views/signaler.js', 'js/views/verification.js', 'js/views/plan.js', 'js/views/scenarios.js', 'js/views/arrondissement.js', 'js/views/jury.js', 'js/views/droits.js', 'js/views/commun.js', 'js/views/accueil.js', 'js/views/confidentialite.js',
  'js/views/connexion.js', 'js/views/suivi.js', 'js/views/importer.js', 'js/installer.js', 'js/reprise.js', 'js/views/points.js', 'js/views/precollecteur.js', 'js/views/brigade.js', 'js/views/mairie.js', 'js/views/admin.js',
  'data/droits.json', 'data/pack/commune.geojson', 'data/pack/secteurs.geojson', 'data/pack/eau.geojson', 'data/pack/routes.geojson', 'data/pack/sites_candidats.geojson', 'data/pack/infrastructures.geojson',
  'vendor/maplibre/maplibre-gl.js', 'vendor/maplibre/maplibre-gl.css', 'icons/icon-192.png', ...FOND];

self.addEventListener('install', (e) => { e.waitUntil(caches.open(V).then((c) => Promise.all(SHELL.map((u) => c.add(new Request(u, { cache: 'reload' })).catch(() => {})))).then(() => self.skipWaiting())); });
self.addEventListener('activate', (e) => { e.waitUntil(caches.keys().then((k) => Promise.all(k.filter((x) => x !== V && x !== VM).map((x) => caches.delete(x)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin || u.pathname.startsWith('/api/')) return;
  if (u.pathname.startsWith('/vendor/masquage/')) {   // fichiers lourds et figés : cache d'abord, sans revérification
    e.respondWith(caches.open(VM).then(async (c) => {
      const hit = await c.match(e.request, { ignoreSearch: true }); if (hit) return hit;
      const r = await fetch(e.request); if (r.ok) c.put(e.request, r.clone()); return r;
    }));
    return;
  }
  // Cache d'abord, puis mise a jour en arriere-plan : economise le reseau.
  e.respondWith(caches.open(V).then(async (c) => {
    const hit = await c.match(e.request, { ignoreSearch: true });
    const net = fetch(e.request, { cache: 'no-cache' }).then((r) => { if (r.ok) c.put(e.request, r.clone()); return r; }).catch(() => hit || (e.request.mode === 'navigate' ? c.match('index.html') : Response.error()));
    return hit || net;
  }));
});
self.addEventListener('sync', (e) => { if (e.tag === 'oregdo-sync') e.waitUntil(self.clients.matchAll().then((l) => l.forEach((c) => c.postMessage('sync')))); });
