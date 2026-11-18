import { $, esc, nf, toast, erreurTexte } from '../util.js';
import { get } from '../api.js';
import * as M from '../map.js';
import { sousNav, PLANS } from '../sousnav.js';

const pct = (x) => nf(x * 100, 0) + ' %';
const bbox = (geom) => {
  const pts = []; (function r(a) { if (typeof a[0] === 'number') pts.push(a); else a.forEach(r); })(geom.coordinates);
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  return [[Math.min(...xs), Math.min(...ys)], [Math.max(...xs), Math.max(...ys)]];
};
function poserContour(contour) {
  const map = M.getMap(); if (!map) return;
  const fc = { type: 'FeatureCollection', features: contour ? [contour] : [] };
  if (map.getSource('arr-contour')) { map.getSource('arr-contour').setData(fc); return; }
  map.addSource('arr-contour', { type: 'geojson', data: fc });
  map.addLayer({ id: 'arr-contour-fond', type: 'fill', source: 'arr-contour', paint: { 'fill-color': '#0057c8', 'fill-opacity': 0.08 } });
  map.addLayer({ id: 'arr-contour-trait', type: 'line', source: 'arr-contour', paint: { 'line-color': '#0057c8', 'line-width': 3, 'line-dasharray': [2, 1] } });
}

// ----- sorties exploitables du plan : fichiers pour la mairie et feuilles de route à imprimer -----
const csvCell = (v) => { const s = String(v ?? ''); return /[";\n,]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
const csv = (lignes) => '﻿' + lignes.map((l) => l.map(csvCell).join(';')).join('\r\n');          // BOM + point-virgule : s'ouvre correctement dans Excel en français
function telecharger(nom, contenu, type) {
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([contenu], { type })); a.download = nom;
  document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}
const TYPES = { pr: 'Point de regroupement', depotoir: 'Dépotoir vérifié' };
export function csvPoints(p) {
  const f = p.pr.features, cles = [...new Set(f.flatMap((x) => Object.keys(x.properties)))].filter((k) => !k.startsWith('_'));
  return csv([['id', 'longitude', 'latitude', ...cles.filter((k) => k !== 'id')], ...f.map((x) => [x.properties.id, x.geometry.coordinates[0], x.geometry.coordinates[1], ...cles.filter((k) => k !== 'id').map((k) => x.properties[k])])]);
}
export function csvTournees(p) {
  const l = [['camion', 'voyage', 'ordre', 'type', 'identifiant', 'kg_a_charger', 'charge_totale_voyage_kg', 'distance_voyage_km']];
  for (const t of p.tournees.features) t.properties.arrets.forEach((a, i) => l.push([t.properties.camion + 1, t.properties.voyage, i + 1, TYPES[a.type] || a.type, a.id, Math.round(a.kg), Math.round(t.properties.charge_kg), t.properties.distance_km]));
  return csv(l);
}
export function feuillesDeRoute(p) {
  const a = p.arrondissement, jour = new Date().toLocaleDateString('fr-FR'), freq = p.scenario?.frequence_collecte_jours;
  const feuilles = [...p.tournees.features].sort((x, y) => x.properties.camion - y.properties.camion || x.properties.voyage - y.properties.voyage).map((t) => `
    <article class="feuille-route"><h2>Camion ${esc(t.properties.camion + 1)} · voyage ${esc(t.properties.voyage)}</h2>
      <p>${esc(a.nom)} · plan du ${esc(jour)}${freq ? (+freq === 1 ? ' · passage quotidien' : ` · passage tous les ${esc(freq)} jours`) : ''}</p>
      <p><b>${esc(nf(t.properties.distance_km, 1))} km</b> · charge prévue <b>${esc(nf(t.properties.charge_kg))} kg</b> · ${esc(t.properties.arrets.length)} arrêt(s)</p>
      <table><tr><th>Ordre</th><th>Type</th><th>Identifiant</th><th>À charger (kg)</th><th>Fait</th></tr>${t.properties.arrets.map((s, i) => `<tr><td>${i + 1}</td><td>${esc(TYPES[s.type] || s.type)}</td><td>${esc(s.id)}</td><td>${esc(nf(s.kg))}</td><td class="case"></td></tr>`).join('')}</table>
      <p class="petit">Plan cible sur données de démonstration : ordre et quantités à valider avec la mairie avant tout usage sur le terrain. Un arrêt non effectué est noté dans « Fait » et signalé à la mairie.</p></article>`).join('');
  return feuilles || '<p>Aucune tournée ne traverse cet arrondissement dans le plan actuel.</p>';
}
function imprimer(p) {
  document.getElementById('feuilles')?.remove();
  const z = document.createElement('section'); z.id = 'feuilles'; z.innerHTML = feuillesDeRoute(p); document.body.append(z);
  const fin = () => { z.remove(); window.removeEventListener('afterprint', fin); }; window.addEventListener('afterprint', fin);
  window.print();
}

export async function render(racine) {
  racine.innerHTML = `${sousNav(PLANS, 'arrondissement')}<h2>Plan de gestion d'un arrondissement</h2>
  <div class="alerte" id="avert"><b>Contours synthétiques.</b> Le découpage en arrondissements est à remplacer par les limites officielles ; les chiffres sont des estimations de planification.</div>
  <label for="choix">Arrondissement</label> <select id="choix" aria-label="Choisir un arrondissement"></select>
  <div id="kpi" aria-live="polite"></div>
  <div class="carte-zone" style="flex:none;height:320px;margin-top:10px"><div class="cible" id="cible-carte"></div></div>
  <h3>Les 12 arrondissements, du moins bien au mieux desservi</h3><div id="tableau"></div>`;
  let vivant = true; const ok = () => vivant && $('#kpi');
  await M.montrer($('#cible-carte'));
  M.visible(['sig', 'dep', 'avant'], false); M.visible(['pr', 'tournees'], true);
  const carte = M.getMap(); if (carte && !carte.isStyleLoaded()) await new Promise((r) => carte.once('idle', r));
  let tab;
  try { tab = await get('/api/plan/arrondissements'); } catch (e) { toast(erreurTexte(e)); return () => { vivant = false; }; }
  if (!ok()) return;
  const l = tab.arrondissements;
  $('#choix').innerHTML = l.map((x) => `<option value="${esc(x.code)}">${esc(x.nom)} (${pct(x.couverture_population)} desservis)</option>`).join('');
  $('#tableau').innerHTML = `<div class="defile"><table><tr><th>Arrondissement</th><th>Habitants</th><th>Desservis</th><th>PR</th><th>Dépotoirs vérifiés</th><th>Non desservi (t/j)</th></tr>${l.map((x) => `<tr data-c="${esc(x.code)}" style="cursor:pointer"><td><b>${esc(x.nom)}</b></td><td>${nf(x.population)}</td><td>${pct(x.couverture_population)}</td><td>${nf(x.nb_pr)}</td><td>${nf(x.nb_depotoirs_verifies)}</td><td>${nf(x.ecart_non_desservi_t_j, 1)}</td></tr>`).join('')}</table></div>`;
  const montrer = async (code) => {
    $('#kpi').innerHTML = '<p class="mut">Chargement…</p>';
    try {
      const p = await get('/api/plan/arrondissement/' + encodeURIComponent(code));
      if (!ok()) return;
      const a = p.arrondissement;
      $('#kpi').innerHTML = `<h3>${esc(a.nom)}</h3><p class="mut">${nf(a.population)} habitants · ${nf(a.nb_secteurs)} secteurs · ${nf(a.nb_ilots)} îlots · rang ${nf(a.rang_couverture)} sur 12 (1 = le moins bien desservi)</p>
      <div class="grille">
        <div class="carte"><b>${pct(a.couverture_population)}</b><br><span class="petit">des habitants desservis par un point de regroupement</span></div>
        <div class="carte"><b>${nf(a.nb_pr)} PR</b><br><span class="petit">charge ${nf(a.charge_pr_t_j, 1)} t/j pour une capacité de ${nf(a.capacite_pr_t_j, 1)} t/j</span></div>
        <div class="carte"><b>${nf(a.tonnes_a_collecter_j, 1)} t/j à collecter</b><br><span class="petit">${nf(a.tonnes_produites_j, 1)} t produites${a.tonnes_valorisees_j ? `, dont ${nf(a.tonnes_valorisees_j, 1)} t triées et revendues` : ''}</span></div>
        <div class="carte"><b>${nf(a.ecart_non_desservi_t_j, 1)} t/j non desservies</b><br><span class="petit">écart entre ce qu'il faut collecter et la charge des PR</span></div>
        <div class="carte"><b>${nf(a.nb_depotoirs_verifies)} dépotoir(s) vérifié(s)</b><br><span class="petit">dans le plan de tournées</span></div>
        <div class="carte"><b>${nf(a.nb_voyages)} voyages · ${nf(a.distance_voyages_km, 1)} km</b><br><span class="petit">des tournées qui traversent l'arrondissement</span></div>
      </div><p class="petit mut">Installation des PR : ${nf(a.cout_installation_pr_fcfa / 1e6, 1)} M FCFA. ${esc(p.avertissement)}</p>
      <div class="choix" id="sorties" role="group" aria-label="Exporter ce plan"><button class="primaire" id="b-feuilles" type="button">Feuilles de route (imprimer)</button><button class="secondaire" id="b-csv-pr" type="button">Points de regroupement (CSV)</button><button class="secondaire" id="b-csv-t" type="button">Tournées (CSV)</button><button class="secondaire" id="b-geo" type="button">Plan complet (GeoJSON)</button></div>`;
      $('#b-feuilles').onclick = () => imprimer(p);
      $('#b-csv-pr').onclick = () => telecharger(`oregdo-${a.code}-points.csv`, csvPoints(p), 'text/csv;charset=utf-8');
      $('#b-csv-t').onclick = () => telecharger(`oregdo-${a.code}-tournees.csv`, csvTournees(p), 'text/csv;charset=utf-8');
      $('#b-geo').onclick = () => telecharger(`oregdo-${a.code}-plan.geojson`, JSON.stringify({ type: 'FeatureCollection', features: [p.contour, ...p.pr.features, ...p.tournees.features], properties: { arrondissement: a.nom, synthetique: true, avertissement: p.avertissement } }), 'application/geo+json');
      M.donnees('pr', p.pr); M.donnees('tournees', p.tournees); poserContour(p.contour);
      if (carte) carte.fitBounds(bbox(p.contour.geometry), { padding: 30, duration: 600 });
      $('#choix').value = code;
    } catch (e) { if (ok()) $('#kpi').innerHTML = `<p class="alerte err">${esc(erreurTexte(e))}</p>`; }
  };
  $('#choix').onchange = (e) => montrer(e.target.value);
  $('#tableau').onclick = (e) => { const tr = e.target.closest('tr[data-c]'); if (tr) { montrer(tr.dataset.c); $('#kpi').scrollIntoView({ block: 'start' }); } };
  montrer(l[0].code);
  return () => { vivant = false; try { poserContour(null); } catch (e) { /* carte déjà détruite */ } };
}
