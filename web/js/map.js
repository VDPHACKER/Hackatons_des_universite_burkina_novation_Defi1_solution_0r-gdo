import { commune } from './commune.js';
// Carte MapLibre partagée. Fond de carte construit à partir des données OpenStreetMap du pack (hors ligne, voir
// scripts/build_osm_layers.py) : routes hiérarchisées, rues de quartier chargées à la demande, noms de quartiers et de communes,
// repères (hôpitaux, marchés, écoles), espaces verts, eau et décharges déjà cartographiées dans OSM.
// Les noms utilisent des polices locales (vendor/fonts). Tuiles OSM en ligne : option « Fond OSM ».
import { fc } from './util.js';
const FC0 = { type: 'FeatureCollection', features: [] };
let FOND = 'data/pack/fond/';           // fixé au démarrage d'après la commune servie
const ZOOM_RUES = 12.5;
let map, ready, lib, ruesChargees = false;
export const getMap = () => map;
// Groupes de couches activables depuis l'écran « Carte ».
export const GROUPES = {
  rues: ['rues-c', 'rues'],
  decharges: ['decharges-f', 'decharges-l'],
  reperes: ['rep1-c', 'rep1-n', 'rep2-c', 'rep2-n', 'rep3-c', 'rep3-n'],
  quartiers: ['lieux-grands', 'lieux-quartiers', 'lieux-petits'],
  communes: ['communes-l', 'communes-n'],
  secteurs: ['secteurs-f', 'secteurs-l'],
};
function charger() {
  if (lib) return lib;
  lib = new Promise((res, rej) => {
    const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = 'vendor/maplibre/maplibre-gl.css'; document.head.append(l);
    const s = document.createElement('script'); s.src = 'vendor/maplibre/maplibre-gl.js'; s.onload = () => res(window.maplibregl); s.onerror = rej; document.head.append(s);
  });
  return lib;
}
export async function montrer(conteneur, opts = {}) {
  FOND = commune().fond;
  const gl = await charger();
  if (!map) {
    const base = location.origin + location.pathname.replace(/[^/]*$/, '');
    map = new gl.Map({
      container: conteneur, center: commune().centre, zoom: commune().zoom, minZoom: 8,
      style: { version: 8, glyphs: base + 'vendor/fonts/{fontstack}/{range}.pbf', sources: {}, layers: [{ id: 'fond', type: 'background', paint: { 'background-color': '#f1efe9' } }] },
      attributionControl: { compact: true, customAttribution: 'Données © contributeurs OpenStreetMap (ODbL) · Orẽgdo' },
    });
    map.addControl(new gl.NavigationControl({ showCompass: false }), 'top-right');
    map.addControl(new gl.GeolocateControl({ trackUserLocation: false }), 'top-right');
    ready = new Promise((r) => map.on('load', r));
    await ready; await couches();
    map.on('zoomend', chargerRues);
  } else {
    conteneur.append(map.getContainer());
    setTimeout(() => map.resize(), 50);
  }
  return map;
}

// Symboles de la carte, dessinés ici (aucune image à charger, donc disponibles hors ligne). 64 px = 32 px à l'écran (pixelRatio 2).
const toile = (dessin) => { const c = document.createElement('canvas'); c.width = c.height = 64; const g = c.getContext('2d'); g.lineJoin = 'round'; g.lineCap = 'round'; dessin(g); return g.getImageData(0, 0, 64, 64); };
const rond = (g, x, y, r, rempli, bord = '#fff', epaisseur = 4) => { g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fillStyle = rempli; g.fill(); g.lineWidth = epaisseur; g.strokeStyle = bord; g.stroke(); };
function icones() {
  const ajoute = (nom, dessin) => { if (!map.hasImage(nom)) map.addImage(nom, toile(dessin), { pixelRatio: 2 }); };
  ajoute('i-depot', (g) => {                                   // dépotoir : triangle rouge avec point d'exclamation
    g.beginPath(); g.moveTo(32, 7); g.lineTo(58, 54); g.lineTo(6, 54); g.closePath(); g.fillStyle = '#d92d20'; g.fill(); g.lineWidth = 5; g.strokeStyle = '#fff'; g.stroke();
    g.fillStyle = '#fff'; g.fillRect(29, 22, 6, 17); g.beginPath(); g.arc(32, 46, 3.6, 0, Math.PI * 2); g.fill();
  });
  ajoute('i-verifie', (g) => {                                 // signalement vérifié : cercle vert avec coche
    rond(g, 32, 32, 25, '#12a150'); g.beginPath(); g.moveTo(20, 33); g.lineTo(29, 42); g.lineTo(45, 24); g.lineWidth = 6; g.strokeStyle = '#fff'; g.stroke();
  });
  ajoute('i-confirmer', (g) => {                               // à confirmer : cercle ambre avec point d'interrogation
    rond(g, 32, 32, 25, '#f59e0b'); g.fillStyle = '#fff'; g.font = '800 36px "Source Sans 3", sans-serif'; g.textAlign = 'center'; g.fillText('?', 32, 44);
  });
  ajoute('i-rejete', (g) => {                                  // rejeté : petit cercle gris, discret
    rond(g, 32, 32, 19, '#8b97a8', '#fff', 3.5); g.beginPath(); g.moveTo(25, 25); g.lineTo(39, 39); g.moveTo(39, 25); g.lineTo(25, 39); g.lineWidth = 4.5; g.strokeStyle = '#fff'; g.stroke();
  });
  ajoute('i-pr', (g) => {                                      // point de regroupement : épingle bleue
    g.beginPath(); g.moveTo(32, 61); g.bezierCurveTo(14, 42, 11, 33, 11, 25); g.arc(32, 25, 21, Math.PI, 0); g.bezierCurveTo(53, 33, 50, 42, 32, 61); g.closePath();
    g.fillStyle = '#1e7a46'; g.fill(); g.lineWidth = 4; g.strokeStyle = '#fff'; g.stroke(); g.beginPath(); g.arc(32, 25, 8, 0, Math.PI * 2); g.fillStyle = '#fff'; g.fill();
  });
  ajoute('i-cet', (g) => {                                     // centre d'enfouissement : carré marine
    g.beginPath(); g.roundRect(8, 8, 48, 48, 10); g.fillStyle = '#0b2a5b'; g.fill(); g.lineWidth = 4; g.strokeStyle = '#fff'; g.stroke();
    g.fillStyle = '#fff'; g.fillRect(18, 38, 28, 6); g.fillRect(22, 28, 20, 6); g.fillRect(27, 18, 10, 6);
  });
  ajoute('i-camion', (g) => {                                  // camion : disque bleu avec silhouette
    rond(g, 32, 32, 25, '#2f6f9f'); g.fillStyle = '#fff'; g.fillRect(16, 23, 19, 15); g.beginPath(); g.moveTo(36, 28); g.lineTo(43, 28); g.lineTo(48, 34); g.lineTo(48, 38); g.lineTo(36, 38); g.closePath(); g.fill();
    rond(g, 24, 41, 4.2, '#2f6f9f', '#fff', 2.6); rond(g, 41, 41, 4.2, '#2f6f9f', '#fff', 2.6);
  });
}
const taille = (a, b, c) => ['interpolate', ['linear'], ['zoom'], 10, a, 14, b, 17, c];

const src = (id, data = FC0) => map.addSource(id, { type: 'geojson', data });
const lire = (nom, dossier = FOND) => fetch(dossier + nom).then((r) => r.json());
const POLICE = ['OpenSans-Regular'], GRAS = ['OpenSans-Bold'];
const cls = (a, b, c, d) => ['match', ['get', 'c'], 'motorway', a, 'trunk', a, 'primary', b, 'secondary', c, d];
const halo = { 'text-halo-color': '#ffffff', 'text-halo-width': 1.6 };

// Rues de quartier (16 Mo bruts, ~4 Mo compressés) : chargées seulement quand on zoome, jamais en mode économie de données.
export async function chargerRues() {
  if (ruesChargees || !map || document.body.classList.contains('eco') || map.getZoom() < ZOOM_RUES) return;
  if (map.getLayoutProperty('rues', 'visibility') === 'none') return;
  ruesChargees = true;
  try { map.getSource('rues-src').setData(await lire('routes_locales.geojson')); } catch (e) { ruesChargees = false; }
}

async function couches() {
  const eco = document.body.classList.contains('eco');
  const [com, sec, eau] = await Promise.all(['commune', 'secteurs', 'eau'].map((n) => lire(n + '.geojson', commune().pack)));
  ['communes', 'verts', 'decharges', 'rues-src', 'rp', 'lieux', 'reperes'].forEach((i) => src(i));
  src('secteurs', sec); src('commune', com); src('eau', eau);
  ['sig', 'dep', 'pr', 'tournees', 'camions', 'avant', 'sites', 'cet', 'dessin'].forEach((i) => src(i));

  // --- fond : surfaces
  map.addLayer({ id: 'verts', type: 'fill', source: 'verts', paint: { 'fill-color': ['match', ['get', 't'], 'forest', '#bfdcb3', 'wood', '#bfdcb3', 'cemetery', '#dbe3d3', '#d3e8c9'], 'fill-opacity': 0.85 } });
  map.addLayer({ id: 'eau', type: 'fill', source: 'eau', paint: { 'fill-color': '#b6d6ee', 'fill-opacity': 1 } });
  map.addLayer({ id: 'secteurs-f', type: 'fill', source: 'secteurs', paint: { 'fill-color': '#7ba58a', 'fill-opacity': 0.04 } });
  map.addLayer({ id: 'secteurs-l', type: 'line', source: 'secteurs', paint: { 'line-color': '#9aa89f', 'line-width': 0.8, 'line-dasharray': [2, 3] } });
  map.addLayer({ id: 'decharges-f', type: 'fill', source: 'decharges', paint: { 'fill-color': '#b5651d', 'fill-opacity': 0.4 } });
  map.addLayer({ id: 'decharges-l', type: 'line', source: 'decharges', paint: { 'line-color': '#8a4b14', 'line-width': 1.2 } });
  // --- fond : routes (rues de quartier sous les routes principales)
  const rond = { 'line-cap': 'round', 'line-join': 'round' };
  map.addLayer({ id: 'rues-c', type: 'line', source: 'rues-src', minzoom: ZOOM_RUES, layout: rond, paint: { 'line-color': '#c4bfb1', 'line-width': ['interpolate', ['linear'], ['zoom'], 12.5, 1.1, 15, 4.4, 18, 13] } });
  map.addLayer({ id: 'rues', type: 'line', source: 'rues-src', minzoom: ZOOM_RUES, layout: rond, paint: { 'line-color': '#ffffff', 'line-width': ['interpolate', ['linear'], ['zoom'], 12.5, 0.5, 15, 2.6, 18, 10.5] } });
  map.addLayer({ id: 'rp-c', type: 'line', source: 'rp', layout: rond, paint: { 'line-color': '#9894bd', 'line-width': ['interpolate', ['linear'], ['zoom'], 9, cls(2.4, 2, 1.6, 1.2), 13, cls(6.5, 5.5, 4.5, 3.5), 18, cls(22, 18, 14, 11)] } });
  map.addLayer({ id: 'rp', type: 'line', source: 'rp', layout: rond, paint: { 'line-color': ['match', ['get', 'c'], 'motorway', '#bdb9dc', 'trunk', '#bdb9dc', 'primary', '#cecbe6', 'secondary', '#dedcee', '#ffffff'], 'line-width': ['interpolate', ['linear'], ['zoom'], 9, cls(1.2, 1, 0.8, 0.5), 13, cls(4.5, 3.8, 3, 2.2), 18, cls(19, 15, 11.5, 8.5)] } });
  map.addLayer({ id: 'rp-n', type: 'symbol', source: 'rp', minzoom: 13, layout: { 'symbol-placement': 'line', 'text-field': ['coalesce', ['get', 'n'], ['get', 'r']], 'text-font': POLICE, 'text-size': 11, 'symbol-spacing': 320 }, paint: { 'text-color': '#6b6896', ...halo } });
  // --- limites : communes voisines et commune de Ouagadougou
  map.addLayer({ id: 'communes-l', type: 'line', source: 'communes', paint: { 'line-color': '#d6477a', 'line-width': 1.4, 'line-dasharray': [3, 2.5] } });
  map.addLayer({ id: 'communes-n', type: 'symbol', source: 'communes', maxzoom: 12, layout: { 'text-field': ['get', 'nom'], 'text-font': POLICE, 'text-size': 13, 'text-transform': 'uppercase', 'text-letter-spacing': 0.25 }, paint: { 'text-color': '#c9709a', 'text-opacity': 0.85, ...halo } });
  map.addLayer({ id: 'commune', type: 'line', source: 'commune', paint: { 'line-color': '#0b2a5b', 'line-width': 1.6, 'line-opacity': 0.7 } });
  // --- repères (trois niveaux d'importance, du plus visible au plus détaillé)
  const COUL = ['match', ['get', 't'], 'hospital', '#d93025', 'clinic', '#e8710a', 'pharmacy', '#188038', 'school', '#7b5ea7', 'college', '#7b5ea7', 'university', '#5b3d99', 'marketplace', '#c26a00', 'bus_station', '#1a73e8', 'townhall', '#202124', 'police', '#174ea6', '#5f6368'];
  [['rep1', ['<=', ['get', 'z'], 2], 12.5], ['rep2', ['all', ['>', ['get', 'z'], 2], ['<=', ['get', 'z'], 4]], 14.5], ['rep3', ['>', ['get', 'z'], 4], 16]].forEach(([id, filtre, minzoom]) => {
    map.addLayer({ id: id + '-c', type: 'circle', source: 'reperes', minzoom, filter: filtre, paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 12.5, 3.5, 17, 6], 'circle-color': COUL, 'circle-stroke-color': '#fff', 'circle-stroke-width': 1.5 } });
    map.addLayer({ id: id + '-n', type: 'symbol', source: 'reperes', minzoom: minzoom + 0.5, filter: filtre, layout: { 'text-field': ['get', 'nom'], 'text-font': POLICE, 'text-size': 11, 'text-offset': [0, 0.9], 'text-anchor': 'top', 'text-max-width': 8 }, paint: { 'text-color': COUL, ...halo } });
  });
  // --- noms de quartiers et de villes
  const txt = (taille, gras, maj) => ({ 'text-field': ['get', 'nom'], 'text-font': gras ? GRAS : POLICE, 'text-size': taille, 'text-transform': maj ? 'uppercase' : 'none', 'text-letter-spacing': maj ? 0.1 : 0, 'text-max-width': 7 });
  map.addLayer({ id: 'lieux-grands', type: 'symbol', source: 'lieux', minzoom: 8, filter: ['in', ['get', 't'], ['literal', ['city', 'town']]], layout: txt(15, true, true), paint: { 'text-color': '#3c4043', ...halo } });
  map.addLayer({ id: 'lieux-quartiers', type: 'symbol', source: 'lieux', minzoom: 9.5, filter: ['==', ['get', 't'], 'suburb'], layout: txt(13, true, true), paint: { 'text-color': '#3c4043', ...halo } });
  map.addLayer({ id: 'lieux-petits', type: 'symbol', source: 'lieux', minzoom: 10.5, filter: ['in', ['get', 't'], ['literal', ['neighbourhood', 'quarter', 'village']]], layout: txt(12, false, true), paint: { 'text-color': '#4a4f55', ...halo } });
  // --- données de l'outil, au-dessus du fond : de petits symboles distincts (forme + couleur), qui se masquent s'ils se chevauchent
  icones();
  const coul = ['match', ['%', ['to-number', ['get', 'camion'], 0], 5], 0, '#d1007a', 1, '#1565d8', 2, '#c46a00', 3, '#6b2fb3', '#00776e'];
  map.addLayer({ id: 'avant', type: 'line', source: 'avant', paint: { 'line-color': '#777', 'line-width': 2.5, 'line-dasharray': [1, 2], 'line-opacity': 0.8 } });
  map.addLayer({ id: 'tournees-c', type: 'line', source: 'tournees', layout: rond, paint: { 'line-color': '#ffffff', 'line-width': ['interpolate', ['linear'], ['zoom'], 9, 2.6, 14, 4.8, 17, 7], 'line-opacity': ['interpolate', ['linear'], ['zoom'], 10, 0.25, 13, 0.85] } });
  map.addLayer({ id: 'tournees', type: 'line', source: 'tournees', layout: rond, paint: { 'line-color': coul, 'line-width': ['interpolate', ['linear'], ['zoom'], 9, 1.2, 14, 2.6, 17, 4.2], 'line-opacity': ['interpolate', ['linear'], ['zoom'], 10, 0.35, 13, 0.9] } });
  map.addLayer({ id: 'sites', type: 'circle', source: 'sites', paint: { 'circle-radius': 6, 'circle-color': '#fff', 'circle-stroke-width': 2.5, 'circle-stroke-color': '#6b2fb3' } });
  map.addLayer({ id: 'cet', type: 'symbol', source: 'cet', layout: { 'icon-image': 'i-cet', 'icon-ignore-placement': true, 'icon-size': taille(0.5, 0.7, 0.85), 'icon-allow-overlap': true } });
  map.addLayer({ id: 'camions', type: 'symbol', source: 'camions', layout: { 'icon-image': 'i-camion', 'icon-ignore-placement': true, 'icon-size': taille(0.42, 0.62, 0.78), 'icon-allow-overlap': false } });
  map.addLayer({ id: 'pr', type: 'symbol', source: 'pr', layout: { 'icon-image': 'i-pr', 'icon-ignore-placement': true, 'icon-anchor': 'bottom', 'icon-size': taille(0.36, 0.58, 0.76), 'icon-allow-overlap': false, 'icon-padding': 2 } });
  map.addLayer({ id: 'dep', type: 'symbol', source: 'dep', layout: { 'icon-image': 'i-depot', 'icon-ignore-placement': true, 'icon-size': taille(0.5, 0.74, 0.92), 'icon-allow-overlap': false, 'icon-padding': 3, 'symbol-sort-key': 0 } });
  map.addLayer({ id: 'sig', type: 'symbol', source: 'sig', layout: {
    'icon-image': ['match', ['get', 'statut'], 'verifie', 'i-verifie', 'a_confirmer', 'i-confirmer', 'i-rejete'],
    'icon-size': ['interpolate', ['linear'], ['zoom'], 10, ['match', ['get', 'statut'], 'rejete', 0.3, 0.42], 14, ['match', ['get', 'statut'], 'rejete', 0.44, 0.6], 17, ['match', ['get', 'statut'], 'rejete', 0.55, 0.74]],
    'icon-allow-overlap': false, 'icon-ignore-placement': true, 'icon-padding': 2, 'symbol-sort-key': ['match', ['get', 'statut'], 'verifie', 1, 'a_confirmer', 2, 3] } });
  map.addLayer({ id: 'dessin', type: 'line', source: 'dessin', paint: { 'line-color': '#d1007a', 'line-width': 3 } });
  const ci = await lire('infrastructures.geojson', commune().pack);
  map.getSource('cet').setData({ ...ci, features: ci.features });
  // Couches légères d'abord ; les rues de quartier suivent au zoom. Mode économie : routes principales, quartiers et limites seulement.
  const charge = [['rp', 'routes_principales.geojson'], ['communes', 'communes.geojson'], ['lieux', 'lieux.geojson']];
  if (!eco) charge.push(['verts', 'verts.geojson'], ['decharges', 'decharges_osm.geojson'], ['reperes', 'reperes.geojson']);
  charge.forEach(([id, nom]) => lire(nom).then((d) => map.getSource(id).setData(d)).catch(() => {}));
  if (eco) visible([...GROUPES.rues, ...GROUPES.reperes, ...GROUPES.decharges], false);
  chargerRues();
}
export function donnees(id, data) {
  if (map && map.getSource(id)) map.getSource(id).setData(fc(data));
  if (id === 'tournees' && map && map.getSource('camions')) {            // un camion au milieu de chaque tournée (comme sur la maquette)
    const pts = fc(data).features.filter((f) => f.geometry && f.geometry.type === 'LineString' && f.geometry.coordinates.length > 1)
      .map((f) => ({ type: 'Feature', properties: { camion: f.properties.camion }, geometry: { type: 'Point', coordinates: f.geometry.coordinates[Math.floor(f.geometry.coordinates.length / 2)] } }));
    map.getSource('camions').setData({ type: 'FeatureCollection', features: pts });
  }
}
export function visible(couches, v) {
  const layers = couches.flatMap((l) => (l === 'tournees' ? ['tournees-c', 'tournees', 'camions'] : [l]));
  layers.forEach((l) => map && map.getLayer(l) && map.setLayoutProperty(l, 'visibility', v ? 'visible' : 'none'));
  if (v && layers.includes('rues')) chargerRues();
}
export function filtrerStatuts(liste) { if (map && map.getLayer('sig')) map.setFilter('sig', ['in', ['get', 'statut'], ['literal', liste]]); }
export function fond(osm) {
  if (!map) return;
  if (osm && !map.getSource('osm')) {
    map.addSource('osm', { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, maxzoom: 19, attribution: '© OpenStreetMap contributors' });
    map.addLayer({ id: 'osm', type: 'raster', source: 'osm' }, 'verts');
  }
  if (map.getLayer('osm')) map.setLayoutProperty('osm', 'visibility', osm ? 'visible' : 'none');
}
export function cliquer(layer, f) { map.on('click', layer, (e) => f(e.features[0], e)); map.on('mouseenter', layer, () => (map.getCanvas().style.cursor = 'pointer')); map.on('mouseleave', layer, () => (map.getCanvas().style.cursor = '')); }
export function centrer(lon, lat, z = 15) { map && map.flyTo({ center: [lon, lat], zoom: z }); }
export function enregistrerSouris(f) { map.on('click', f); return () => map.off('click', f); }
