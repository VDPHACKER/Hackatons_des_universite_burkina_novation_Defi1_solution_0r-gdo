import { commune } from '../commune.js';
import { $, esc, nf, toast, normList, erreurTexte, okMotif, badge, propre } from '../util.js';
import { get, post, lirePlan, lireKpi, reinitialiserScenario } from '../api.js';
import { kpiHtml } from '../kpi.js';
import * as M from '../map.js';
import { sousNav, SIMULATION } from '../sousnav.js';

function verdictPieges(r) {
  const l = r.resultats || [];
  if (!l.length && !r.resume) return '';
  const c = r.resume || {};
  const compte = (s) => l.filter((x) => x.statut === s).length;
  const v = c.verifies ?? compte('verifie'), a = c.a_confirmer ?? compte('a_confirmer'), rj = c.rejetes ?? compte('rejete');
  const tot = l.length || v + a + rj;
  const lignes = l.slice(0, 30).map((x) => `<tr><td>${esc(x.id)}</td><td>${badge(x.statut)}</td><td>${esc(Math.round(x.score ?? 0))}</td><td>${(x.motifs || []).filter((m) => okMotif(m) === false).slice(0, 2).map((m) => esc(propre(m.motif || m.message))).join('<br>') || '-'}</td></tr>`).join('');
  return `<div class="carte" style="border-color:${v ? 'var(--rej)' : 'var(--ok)'}"><h4 style="margin:0">Verdict sur les signalements piégés</h4>
  <p style="font-size:1.1rem"><b>${nf(tot)} injectés : ${nf(rj)} rejetés, ${nf(a)} à confirmer, ${nf(v)} vérifiés.</b> ${v === 0 ? '<span class="delta-b">Aucun ne peut entrer dans le plan.</span>' : '<span class="delta-m">Certains sont vérifiés : ils entrent dans le plan.</span>'}</p>
  ${lignes ? `<details><summary>Voir chaque signalement et ses motifs</summary><div class="defile"><table><tr><th>N°</th><th>Statut</th><th>Score</th><th>Motifs d'échec</th></tr>${lignes}</table></div></details>` : ''}</div>`;
}

export async function render(racine) {
  racine.innerHTML = `${sousNav(SIMULATION, 'jury')}<h2>Console du jury (épreuve en direct)</h2>
  <p class="mut">Chaque bouton applique un aléa, recalcule le plan et affiche l'effet avant/après. Trait gris pointillé : tournées d'avant. Trait coloré : tournées d'après.</p>
  <div class="grille aleas">
    <div class="carte"><b>Panne de camion</b><label for="n-pan">Camions en panne</label><input id="n-pan" type="number" min="1" max="40" value="2"><button class="danger" id="a-panne" style="margin-top:8px">Mettre en panne</button></div>
    <div class="carte"><b>Saison des pluies</b><p class="petit mut">Pistes et zones inondables pénalisées.</p><button class="primaire" id="a-pluie">Déclencher la saison des pluies</button></div>
    <div class="carte"><b>Nouveau quartier</b><label for="sel-sect">Choisir un secteur</label><select id="sel-sect"><option value="">(choisir)</option></select><label for="pop-q">Population ajoutée</label><input id="pop-q" type="number" value="30000" min="1000" step="1000"><div class="choix" style="margin-top:8px"><button class="secondaire" id="b-dessin">Dessiner sur la carte</button><button class="primaire" id="a-quartier">Ajouter le quartier</button></div><p id="dessin-etat" class="petit mut" role="status"></p></div>
    <div class="carte"><b>Signalements piégés</b><label for="n-pie">Nombre</label><input id="n-pie" type="number" min="1" max="100" value="10"><button class="danger" id="a-piege" style="margin-top:8px">Injecter</button></div>
  </div>
  <button class="secondaire" id="a-reset">↺ Remettre la situation de référence</button>
  <div class="carte" id="resume" aria-live="polite"><p class="mut">Aucun aléa appliqué pour le moment.</p></div>
  <div class="carte-zone" style="flex:none;height:360px"><div class="cible" id="cible-carte"></div></div>
  <h3>Journal de l'épreuve</h3><ol id="jr"></ol>`;
  let vivant = true;
  await M.montrer($('#cible-carte'));
  M.visible(['sig', 'dep', 'pr', 'tournees', 'avant'], true); M.visible(['sites'], false);
  M.filtrerStatuts(['verifie', 'a_confirmer', 'rejete']);
  const secteurs = await fetch(commune().pack + 'secteurs.geojson').then((r) => r.json());
  if (!vivant || !$('#sel-sect')) return;
  $('#sel-sect').innerHTML += secteurs.features.map((f) => `<option value="${esc(f.properties.id)}">${esc(f.properties.nom)} (${nf(f.properties.population)} hab.)</option>`).join('');
  let pts = [], dessine = false, off = null;
  const majDessin = () => { M.donnees('dessin', { type: 'FeatureCollection', features: pts.length > 1 ? [{ type: 'Feature', geometry: { type: 'LineString', coordinates: [...pts, pts[0]] }, properties: {} }] : [] }); $('#dessin-etat').textContent = dessine ? `Touchez la carte pour poser les sommets (${pts.length}). Retouchez « Terminer » pour finir.` : pts.length ? `Polygone de ${pts.length} sommets prêt.` : ''; };
  $('#b-dessin').onclick = () => { dessine = !dessine; if (dessine) { pts = []; off = M.enregistrerSouris((e) => { pts.push([e.lngLat.lng, e.lngLat.lat]); majDessin(); }); $('#b-dessin').textContent = 'Terminer le dessin'; } else { off && off(); $('#b-dessin').textContent = 'Dessiner sur la carte'; } majDessin(); };
  const jr = (t) => { const o = $('#jr'); if (o) o.insertAdjacentHTML('afterbegin', `<li>${new Date().toLocaleTimeString('fr-FR')} : ${esc(t)}</li>`); };
  const lancer = async (type, params, libelle, btn) => {
    btn.disabled = true; M.donnees('avant', {});
    try {
      const avantP = lirePlan(await get('/api/plan')); M.donnees('avant', avantP.tournees);
      const pieges0 = type === 'signalements_pieges';
      const idMax = pieges0 ? Math.max(0, ...normList(await get('/api/signalements?avec_essais=1')).map((s) => +s.id || 0)) : 0;
      const t0 = performance.now();
      const r = await post('/api/alea', { type, params }, 120000);
      const client = (performance.now() - t0) / 1000;
      if (!vivant || !$('#resume')) return;
      const p = lirePlan(r.plan || r); const kAvant = r.avant?.kpi ? lireKpi(r.avant.kpi) : avantP.kpi;
      M.donnees('pr', p.pr); M.donnees('tournees', p.tournees);
      const sig = normList(await get('/api/signalements'));
      // Le serveur ne renvoie pas toujours le verdict des piégés : on le reconstruit avec les signalements créés pendant l'appel.
      if (pieges0 && !r.resultats) r.resultats = sig.filter((s) => (+s.id || 0) > idMax).map((s) => ({ id: s.id, statut: s.statut, score: s.score, motifs: s.motifs, piege: true })); M.donnees('sig', { type: 'FeatureCollection', features: sig.filter((s) => s.lat != null).map((s) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [s.lon, s.lat] }, properties: { id: s.id, statut: s.statut } })) });
      if (!vivant || !$('#resume')) return;
      const srv = p.temps_s ?? r.temps_calcul_s, ok = client < 5;
      const pieges = type === 'signalements_pieges';
      $('#resume').innerHTML = `<h3>${esc(libelle)}</h3><p>${esc(r.message || '')}</p><p>Temps de recalcul : <b>${srv != null ? nf(srv, 2) + ' s (serveur)' : 'non fourni'}</b>, ${nf(client, 2)} s au total <span class="${ok ? 'delta-b' : 'delta-m'}">${ok ? 'Sous 5 s' : 'Plus de 5 s'}</span></p>${verdictPieges(r)}${pieges && !r.resultats?.length && !r.resume ? '<p class="alerte">Le serveur n\'a renvoyé aucun verdict détaillé pour les piégés (aucun signalement créé). Version du serveur à mettre à jour pour voir « rejetés / à confirmer / vérifiés ».</p>' : ''}${pieges && r.plan_modifie === false ? '<p class="mut">Le plan est inchangé : aucun piégé n\'est vérifié.</p>' : ''}<h4>Avant / après</h4>${kpiHtml(p.kpi, kAvant)}`;
      jr(`${libelle} : recalcul en ${nf(client, 2)} s`);
    } catch (e) { const t = erreurTexte(e); toast(t); if ($('#resume')) $('#resume').innerHTML = `<p class="alerte err">${esc(t)}</p>`; jr('Échec : ' + t); }
    finally { btn.disabled = false; }
  };
  $('#a-panne').onclick = (e) => lancer('panne_camion', { camions: +$('#n-pan').value }, `Panne de ${$('#n-pan').value} camion(s)`, e.target);
  $('#a-pluie').onclick = (e) => lancer('saison_pluies', { actif: true }, 'Saison des pluies', e.target);
  $('#a-piege').onclick = (e) => lancer('signalements_pieges', { nombre: +$('#n-pie').value, generer: +$('#n-pie').value }, 'Signalements piégés', e.target);
  $('#a-reset').onclick = async (e) => { e.target.disabled = true; try { await reinitialiserScenario(); toast('Situation de référence rétablie.'); jr('Retour à la situation de référence'); } catch (er) { toast(erreurTexte(er)); } e.target.disabled = false; };
  $('#a-quartier').onclick = (e) => {
    let poly = null; const s = $('#sel-sect').value;
    if (pts.length >= 3 && !dessine) poly = { type: 'Polygon', coordinates: [[...pts, pts[0]]] };
    else if (s) poly = secteurs.features.find((f) => f.properties.id === s).geometry;
    if (!poly) { toast('Choisissez un secteur ou dessinez au moins 3 sommets (puis « Terminer »).'); return; }
    return lancer('nouveau_quartier', { polygone: poly, population: +$('#pop-q').value, secteur: s || undefined }, 'Nouveau quartier', e.target);
  };
  return () => { vivant = false; off && off(); M.donnees('avant', {}); M.donnees('dessin', {}); };
}
