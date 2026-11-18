// Tableau de bord de la mairie : indicateurs, carte, simulation de scénarios, plan proposé, comparatif, signalements récents.
// Tous les chiffres viennent de l'API (rien n'est inventé) ; ils décrivent le plan calculé et les signalements reçus.
import { $, $$, esc, nf, toast, erreurTexte, badge, dateFr, normList } from '../util.js';
import { get, post, put, lirePlan } from '../api.js';
import * as M from '../map.js';
import { icone, symbole } from '../icones.js';
import { commune } from '../commune.js';
import { t } from '../i18n.js';

const pct = (x) => (x == null || isNaN(x) ? '–' : nf(x * 100, 0) + ' %');
const COUL = ['#8a97ad', '#2f6f9f', '#1e7a46'];
const NOMS = ['Actuel', 'Renforcé', 'Économe'];
let clicsOk = false;

const toFC = (l) => ({ type: 'FeatureCollection', features: l.filter((s) => s.lat != null && s.lon != null).map((s) => ({ type: 'Feature',
  geometry: { type: 'Point', coordinates: [+s.lon, +s.lat] },
  properties: { id: s.id, statut: s.statut, score: s.score, taille: s.taille, secteur: s.secteur, date: s.horodatage || s.recu_le || '', motifs: JSON.stringify(s.motifs || []) } })) });
const bbox = (g) => { const p = []; (function r(a) { if (typeof a[0] === 'number') p.push(a); else a.forEach(r); })(g.coordinates);
  const x = p.map((q) => q[0]), y = p.map((q) => q[1]); return [[Math.min(...x), Math.min(...y)], [Math.max(...x), Math.max(...y)]]; };
const kpiT = (cls, ico, valeur, lib, sous) => `<div class="kpi-t ${cls}"><span class="rond">${icone(ico, 28)}</span><div><b>${esc(valeur)}</b><span class="lib">${esc(lib)}</span><small>${esc(sous || '')}</small></div></div>`;

function contour(c) {
  const m = M.getMap(); if (!m) return;
  const fc = { type: 'FeatureCollection', features: c ? [c] : [] };
  if (m.getSource('tdb-arr')) { m.getSource('tdb-arr').setData(fc); return; }
  m.addSource('tdb-arr', { type: 'geojson', data: fc });
  m.addLayer({ id: 'tdb-arr-trait', type: 'line', source: 'tdb-arr', paint: { 'line-color': '#1e7a46', 'line-width': 3, 'line-dasharray': [2, 1] } });
}
async function couchePopulation() {
  const m = M.getMap(); if (!m || m.getSource('tdb-pop')) return;
  const d = await (await fetch('/packs/' + commune().code + '/ilots.geojson')).json();
  m.addSource('tdb-pop', { type: 'geojson', data: d });
  m.addLayer({ id: 'tdb-pop-fill', type: 'fill', source: 'tdb-pop', layout: { visibility: 'none' },
    paint: { 'fill-color': ['step', ['get', 'population'], '#e8f1ff', 500, '#bcd6ff', 1000, '#86b4f5', 2000, '#4d8fe6', 3500, '#1d63cc', 5000, '#0b3a8a'], 'fill-opacity': 0.62 } }, 'sig');
}

export async function render(racine) {
  racine.innerHTML = `<div class="tdb">
    <div class="kpis" id="kpis" aria-live="polite"></div>
    <section class="pan tdb-carte" aria-label="${esc(t('tdb.carte', 'Carte'))}">
      <div class="onglets-c" role="group" aria-label="${esc(t('tdb.vue', 'Vue de la carte'))}"><button data-c="carte" aria-pressed="true">${esc(t('tdb.carte', 'Carte'))}</button><button data-c="population" aria-pressed="false">${esc(t('tdb.population', 'Population'))}</button></div>
      <div class="legende-c" id="legende-c"></div>
      <div class="cible-wrap"><div class="cible" id="cible-carte" role="application" aria-label="${esc(t('tdb.carte_aria', 'Carte des dépotoirs, des points de regroupement et des tournées'))}"></div></div>
      <div class="fiche-c" id="fiche-c" hidden></div>
    </section>
    <aside class="pan sim" id="sim" aria-label="${esc(t('tdb.sim', 'Simulation multi-agents'))}"><p class="mut">Chargement…</p></aside>
    <div class="bas">
      <section class="pan" id="pan-plan" aria-label="${esc(t('tdb.plan', 'Plan de gestion proposé'))}"><p class="mut">Chargement…</p></section>
      <section class="pan" id="pan-scen" aria-label="${esc(t('tdb.scen', 'Scénarios comparatifs'))}"></section>
      <section class="pan" id="pan-rec" aria-label="${esc(t('tdb.rec', 'Signalements récents'))}"><p class="mut">Chargement…</p></section>
    </div></div>`;
  let vivant = true, arr = '', sigs = [], plan = null, stats = null, ref = null, a = null, resultats = null;
  try { arr = localStorage.getItem('oregdo.arr') || ''; } catch (e) { /* ignoré */ }
  const ok = () => vivant && $('#kpis');
  const CLE = 'oregdo.scen.' + commune().code;

  // ---------------------------------------------------------------- carte
  const map = await M.montrer($('#cible-carte'));
  if (!ok()) return () => { vivant = false; };
  M.visible(['sites', 'avant'], false); M.visible(M.GROUPES.secteurs, false); M.visible(['sig', 'dep', 'pr', 'tournees'], true);
  M.filtrerStatuts(['verifie', 'a_confirmer', 'rejete']);
  const fiche = (html) => { const f = $('#fiche-c'); if (!f) return; f.innerHTML = html + '<p><button class="secondaire" data-x style="min-height:34px;padding:2px 10px">Fermer</button></p>'; f.hidden = false; $('[data-x]', f).onclick = () => (f.hidden = true); };
  if (!clicsOk) {
    clicsOk = true;
    M.cliquer('sig', (f) => { const p = f.properties; window.__tdbFiche?.(`<b>Signalement ${esc(p.id)}</b> ${badge(p.statut)}<br>${esc(p.secteur || '')} · ${esc(p.taille || '')} · ${nf(p.score)}/100<br><span class="mut">${esc(dateFr(p.date))}</span><br><a href="#/carte?id=${encodeURIComponent(p.id)}">Ouvrir sur la carte</a>`); });
    M.cliquer('pr', (f) => window.__tdbFiche?.(`<b>Point de regroupement ${esc(f.properties.id)}</b><br>Charge ${nf(f.properties.charge_kg_j / 1000, 1)} t/j sur ${nf(f.properties.capacite_kg_j / 1000, 1)} t/j<br>${nf(f.properties.population_desservie)} habitants desservis`));
  }
  window.__tdbFiche = fiche;
  const legende = (pop) => { $('#legende-c').innerHTML = pop
    ? `<b>Habitants par case de 500 m</b><br><i style="background:#e8f1ff;border:1px solid #9bb"></i>moins de 500 <i style="background:#86b4f5"></i>1 000 <i style="background:#1d63cc"></i>3 500 <i style="background:#0b3a8a"></i>5 000 et plus`
    : `<div>${symbole('depot', 16)} Dépotoir confirmé</div><div>${symbole('verifie', 16)} Signalement vérifié</div><div>${symbole('confirmer', 16)} À confirmer</div><div>${symbole('pr', 16)} Point de regroupement</div><div>${symbole('camion', 16)} Tournée d'un camion</div>`; };
  legende(false);
  $$('.onglets-c button').forEach((b) => (b.onclick = async () => {
    const pop = b.dataset.c === 'population';
    $$('.onglets-c button').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    if (pop) { try { await couchePopulation(); } catch (e) { toast('Population indisponible.'); return; } }
    if (map.getLayer('tdb-pop-fill')) map.setLayoutProperty('tdb-pop-fill', 'visibility', pop ? 'visible' : 'none');
    M.visible(['sig', 'dep'], !pop); legende(pop);
  }));

  // ---------------------------------------------------------------- indicateurs, plan, récents
  const dessinerKpi = () => {
    if (!ok() || !plan) return;
    const k = plan.brut.kpi || {}, s = stats ? stats.signalements : null;
    const couv = a ? a.arrondissement.couverture_population : k.taux_couverture_production;
    $('#kpis').innerHTML =
      kpiT('bleu', 'corbeille', nf(a ? a.arrondissement.nb_depotoirs_verifies : (stats ? stats.depotoirs_verifies : k.nb_depotoirs_verifies)), t('tdb.k1', 'Dépotoirs vérifiés'), a ? a.arrondissement.nom : 'dans le plan de tournées') +
      kpiT('vert', 'signaler', s ? nf(s.total) : '–', t('tdb.k2', 'Signalements reçus'), s ? `${nf(s.par_statut.verifie)} vérifiés · ${nf(s.par_statut.a_confirmer)} à confirmer` : 'commune entière') +
      kpiT('orange', 'camion', nf(k.camions_disponibles), t('tdb.k3', 'Camions disponibles'), `${nf(k.camions_utilises)} utilisés dans les tournées`) +
      kpiT('vert', 'coche', pct(couv), a ? t('tdb.k4a', 'Habitants desservis') : t('tdb.k4', 'Couverture de la production'), a ? 'par un point de regroupement' : 'déchets évacués ou valorisés');
    const des = a ? a.arrondissement.couverture_population : (k.couverture_population != null ? k.couverture_population : couv), non = 1 - des;
    const R = 46, C = 2 * Math.PI * R;
    $('#pan-plan').innerHTML = `<h3>${esc(t('tdb.plan', 'Plan de gestion proposé'))}</h3>
      <div class="donut"><svg width="120" height="120" viewBox="0 0 120 120" role="img" aria-label="${esc(pct(des))} des habitants desservis">
        <circle cx="60" cy="60" r="${R}" fill="none" stroke="#f59e0b" stroke-width="14"/>
        <circle cx="60" cy="60" r="${R}" fill="none" stroke="#16a34a" stroke-width="14" stroke-dasharray="${(C * des).toFixed(1)} ${C.toFixed(1)}" transform="rotate(-90 60 60)"/>
        <text x="60" y="58" text-anchor="middle" font-size="22" font-weight="800" fill="currentColor">${esc(pct(des))}</text><text x="60" y="76" text-anchor="middle" font-size="9" fill="currentColor">couverture</text></svg>
        <div class="lg"><div><i style="background:#16a34a"></i>Desservis <b>${esc(pct(des))}</b></div><div><i style="background:#f59e0b"></i>Non desservis <b>${esc(pct(non))}</b></div></div></div>
      <div class="astuce" id="astuce"><span class="mut">Recherche des emplacements à ajouter…</span></div>`;
  };
  const dessinerRecents = () => {
    if (!ok()) return;
    // Les plus récents d'abord ; une date déclarée dans le futur (données de démonstration) est ignorée au profit de la date de réception.
    const maintenant = Date.now() + 5 * 60 * 1000, quand = (s) => { const d = Date.parse(s.horodatage); return d && d <= maintenant ? s.horodatage : s.recu_le; };
    const l = [...sigs].sort((x, y) => String(quand(y)).localeCompare(String(quand(x)))).slice(0, 4);
    $('#pan-rec').innerHTML = `<h3>${esc(t('tdb.rec', 'Signalements récents'))}<a href="#/rapports">${esc(t('tdb.voir', 'Voir tout'))}</a></h3>` + (l.length
      ? `<ul class="recents">${l.map((s) => `<li><span class="vignette">${icone('corbeille', 22)}</span><span class="txt"><b>Dépotoir ${esc(s.taille || '')} · ${esc(s.secteur || 'secteur inconnu')}</b><small>${esc(dateFr(quand(s)))}</small></span>${badge(s.statut)}</li>`).join('')}</ul>`
      : '<p class="mut">Aucun signalement pour le moment.</p>');
  };

  // ---------------------------------------------------------------- arrondissement choisi dans la barre du haut
  const appliquerArr = async () => {
    a = null;
    if (arr) { try { a = await get('/api/plan/arrondissement/' + encodeURIComponent(arr)); } catch (e) { toast(erreurTexte(e)); } }
    if (!ok()) return;
    if (a) { M.donnees('pr', a.pr); M.donnees('tournees', a.tournees); contour(a.contour); map.fitBounds(bbox(a.contour.geometry), { padding: 40, duration: 600 }); }
    else if (plan) { M.donnees('pr', plan.pr); M.donnees('tournees', plan.tournees); contour(null); map.flyTo({ center: commune().centre, zoom: commune().zoom, duration: 600 }); }
    dessinerKpi();
  };
  const surArr = (e) => { arr = e.detail || ''; appliquerArr(); };
  window.addEventListener('oregdo:arr', surArr);

  // ---------------------------------------------------------------- simulation : 3 scénarios modifiables, comparés côte à côte
  const defauts = () => { const r = ref || {}, c = r.camions_nombre || 20, b = r.budget_pr_fcfa || 6e7, f = r.frequence_collecte_jours || 1, p = commune().population;
    return [{ pop: p, camions: c, freq: f, budget: b }, { pop: p, camions: Math.round(c * 1.5), freq: f, budget: Math.round(b * 1.3 / 1e6) * 1e6 },
      { pop: p, camions: Math.max(1, Math.round(c * 0.75)), freq: Math.min(30, f * 2), budget: Math.round(b * 0.7 / 1e6) * 1e6 }]; };
  let scen = null, actif = 0;
  const mods = (s) => ({ facteur_population: s.pop / commune().population, camions_nombre: +s.camions, frequence_collecte_jours: +s.freq, budget_pr_fcfa: +s.budget });
  const retour = (cls, txt) => { const r = $('#retour'); if (r) { r.className = 'retour ' + cls; r.textContent = txt; r.hidden = false; } };
  const dessinerSim = () => {
    if (!ok()) return;
    const s = scen[actif];
    $('#sim').innerHTML = `<h3>${icone('scenarios', 20)} ${esc(t('tdb.sim', 'Simulation multi-agents'))}</h3>
      <p class="petit mut" style="margin:-4px 0 8px">Testez, comparez, décidez.</p>
      <div class="scen" role="tablist">${scen.map((_, i) => `<button role="tab" aria-selected="${i === actif}" data-i="${i}">Scénario ${i + 1}</button>`).join('')}</div>
      <div class="champ"><label for="f-pop">Population estimée</label><input id="f-pop" type="number" min="100000" step="10000" value="${esc(s.pop)}"></div>
      <div class="champ"><label for="f-cam">Camions disponibles</label><input id="f-cam" type="number" min="1" max="500" value="${esc(s.camions)}"></div>
      <div class="champ"><label for="f-frq">Passage tous les (jours)</label><input id="f-frq" type="number" min="1" max="30" value="${esc(s.freq)}"></div>
      <div class="champ"><label for="f-bud">Budget des points (FCFA)</label><input id="f-bud" type="number" min="0" step="1000000" value="${esc(s.budget)}"></div>
      <button class="primaire lancer" id="lancer">▶ Lancer la simulation</button>
      <div class="retour" id="retour" role="status" hidden></div>
      <p id="appliquer" hidden><button class="secondaire" id="b-appliquer" style="width:100%;margin-top:8px">Appliquer le scénario ${actif + 1} au plan de la commune</button></p>
      <p class="petit mut" style="margin:8px 0 0">Scénario 1 = situation de référence du pack ; 2 et 3 sont des variantes proposées (hypothèses), à modifier librement.</p>`;
    $$('.sim .scen button').forEach((b) => (b.onclick = () => { actif = +b.dataset.i; dessinerSim(); }));
    const lire = () => { const v = (id) => +$(id).value; scen[actif] = { pop: v('#f-pop'), camions: v('#f-cam'), freq: v('#f-frq'), budget: v('#f-bud') }; try { localStorage.setItem(CLE, JSON.stringify(scen)); } catch (e) { /* ignoré */ } };
    ['#f-pop', '#f-cam', '#f-frq', '#f-bud'].forEach((id) => ($(id).onchange = lire));
    $('#lancer').onclick = async (e) => {
      lire(); e.target.disabled = true; retour('attente', 'Calcul des trois scénarios…'); const t0 = performance.now();
      try {
        const r = await post('/api/plan/comparer', { scenarios: scen.map(mods) }, 180000);     // trois plans : jusqu'à ~30 s à Ouagadougou
        resultats = r.scenarios; try { localStorage.setItem(CLE + '.res', JSON.stringify(resultats)); } catch (er) { /* ignoré */ }
        dessinerScen(); retour('', `Simulation terminée avec succès · ${nf((performance.now() - t0) / 1000, 1)} s`); $('#appliquer').hidden = false;
        $('#b-appliquer').onclick = async (ev) => {
          ev.target.disabled = true;
          try { await put('/api/scenario', mods(scen[actif])); plan = lirePlan(await post('/api/plan/recalculer', {}, 120000)); M.donnees('pr', plan.pr); M.donnees('tournees', plan.tournees); a = null; arr = ''; dessinerKpi(); toast('Plan de la commune recalculé.'); }
          catch (er) { retour('err', erreurTexte(er)); }
          ev.target.disabled = false;
        };
      } catch (er) { retour('err', erreurTexte(er)); }
      e.target.disabled = false;
    };
    if (resultats) $('#appliquer').hidden = false;
  };
  const dessinerScen = () => {
    if (!ok()) return;
    const el = $('#pan-scen');
    if (!resultats) { el.innerHTML = `<h3>${esc(t('tdb.scen', 'Scénarios comparatifs'))}</h3><p class="mut">Lancez la simulation pour comparer les trois scénarios (coût, couverture, déchets qui fuient vers les dépotoirs).</p>`; return; }
    const mets = [['Coût par tonne', (k) => k.cout_par_tonne_fcfa, (v) => nf(v) + ' FCFA/t'], ['Couverture', (k) => (k.taux_couverture_production || 0) * 100, (v) => nf(v, 0) + ' %'],
      ['Fuite vers dépotoirs', (k) => k.tonnes_fuite_j, (v) => nf(v, 0) + ' t/j']];
    const val = mets.map(([, f]) => resultats.map((r) => f(r.kpi) || 0)), max = val.map((v) => Math.max(...v, 1e-9));
    el.innerHTML = `<h3>${esc(t('tdb.scen', 'Scénarios comparatifs'))}</h3>
      <div class="barres" role="img" aria-label="Comparaison des scénarios : coût par tonne, couverture, fuite vers les dépotoirs">${mets.map((_, m) => `<div class="grp">${resultats.map((_, i) => `<div class="b" style="height:${Math.max(3, val[m][i] / max[m] * 100).toFixed(0)}%;background:${COUL[i]}" title="${esc(mets[m][0])} : ${esc(mets[m][2](val[m][i]))}"></div>`).join('')}</div>`).join('')}</div>
      <div class="noms">${mets.map((x) => `<span>${esc(x[0])}</span>`).join('')}</div>
      <div class="lgd">${resultats.map((_, i) => `<span><i style="background:${COUL[i]}"></i>Scénario ${i + 1} (${NOMS[i]})</span>`).join('')}</div>
      <div class="defile"><table style="margin-top:8px"><tr><th></th>${resultats.map((_, i) => `<th>S${i + 1}</th>`).join('')}</tr>${mets.map((x, m) => `<tr><td>${esc(x[0])}</td>${resultats.map((_, i) => `<td>${esc(x[2](val[m][i]))}</td>`).join('')}</tr>`).join('')}
        <tr><td>Camions utilisés</td>${resultats.map((r) => `<td>${nf(r.kpi.camions_utilises)} / ${nf(r.kpi.camions_disponibles)}</td>`).join('')}</tr></table></div>`;
  };

  // ---------------------------------------------------------------- chargement des données
  const sur = (p, def) => p.catch((e) => { if (def === undefined) throw e; return def; });
  try {
    const [pl, st, sc, sg, dp] = await Promise.all([get('/api/plan'), sur(get('/api/mairie/kpi'), null), sur(get('/api/scenario'), null), sur(get('/api/signalements'), []), sur(get('/api/depotoirs'), null)]);
    if (!ok()) return () => { vivant = false; };
    plan = lirePlan(pl); stats = st; ref = sc ? sc.reference : null; sigs = normList(sg);
    M.donnees('sig', toFC(sigs)); if (dp) M.donnees('dep', dp); M.donnees('pr', plan.pr); M.donnees('tournees', plan.tournees);
    try { const m = localStorage.getItem(CLE); scen = m ? JSON.parse(m) : null; const r = localStorage.getItem(CLE + '.res'); resultats = r ? JSON.parse(r) : null; } catch (e) { scen = null; }
    if (!Array.isArray(scen) || scen.length !== 3) scen = defauts();
    dessinerKpi(); dessinerRecents(); dessinerSim(); dessinerScen();
    if (arr) appliquerArr();
    // Recommandation : emplacements à ajouter (calcul serveur, quelques secondes) — affichée quand elle arrive.
    get('/api/suggestions/emplacements').then((s) => { const n = ((s && s.features) || []).filter((f) => f.properties.type !== 'decharge').length;
      const z = $('#astuce'); if (z) z.innerHTML = n ? `${icone('ampoule', 18)} <b>${nf(Math.min(n, 3))} nouveaux points de regroupement</b> recommandés pour couvrir les habitants non desservis. <a href="#/plan">Voir le détail</a>` : 'Aucun emplacement supplémentaire à recommander avec le budget actuel.'; }).catch(() => { const z = $('#astuce'); if (z) z.innerHTML = ''; });
  } catch (e) { if (ok()) $('#kpis').innerHTML = `<div class="alerte err" role="alert" style="grid-column:1/-1">${esc(erreurTexte(e))}</div>`; }
  return () => { vivant = false; window.removeEventListener('oregdo:arr', surArr); window.__tdbFiche = null; try { contour(null); } catch (e) { /* carte déjà détruite */ } };
}
