import { commune } from '../commune.js';
import { $, esc, nf, toast, erreurTexte } from '../util.js';
import { get, put, post, lireScenario, ecrireScenario, lirePlan, lireSeries, reinitialiserScenario } from '../api.js';
import { kpiHtml, KPI_DEFS, diagnosticHtml } from '../kpi.js';
import { courbes, COULEURS } from '../charts.js';
import { kvGet, kvSet } from '../db.js';
import { sousNav, SIMULATION } from '../sousnav.js';

const CURS = [
  ['population', 'Population', 1e6, 6e6, 50000, (v) => nf(v) + ' habitants'],
  ['taux_abonnement', "Part des ménages abonnés à un pré-collecteur", 0, 1, 0.01, (v) => nf(v * 100) + ' %'],
  ['camions', 'Camions de la commune', 1, 60, 1, (v) => nf(v) + ' camions'],
  ['frequence', 'Un passage tous les… jours', 1, 7, 1, (v) => nf(v) + ' jour(s)'],
  ['budget', "Budget d'installation des points (FCFA, une fois)", 0, 3e8, 5e6, (v) => nf(v / 1e6) + ' M FCFA'],
  ['taux_tri', "Valorisation : part des ménages qui trient et revendent leurs recyclables", 0, 1, 0.05, (v) => nf(v * 100) + ' %'],
];
const LIB = { depotoirs_tonnes: ['Stock de dépotoirs', 't'], couverture: ['Couverture', '%'], cout_cumule_fcfa: ['Budget consommé (cumul)', 'FCFA'], fuite_tonnes: ['Fuite vers les dépotoirs par jour', 't'] };

// Ce que les acteurs « intelligents » ont fait pendant la simulation : décisions de la mairie, pannes de tricycles.
const acteursHtml = (r) => {
  const d = r.decisions_mairie || [], pannes = Math.max(0, ...(r.serie || []).map((l) => l.tricycles_en_panne || 0));
  if (!d.length && !(r.options && (r.options.mairie_decisionnelle || r.options.agents_individuels))) return '';
  return `<div class="pan" style="margin-top:14px"><h3>Ce que les acteurs ont fait</h3>
    ${r.options.mairie_decisionnelle ? (d.length ? `<ul>${d.map((x) => `<li>${esc(x.message)}</li>`).join('')}</ul><p class="petit mut">Investissement décidé : ${nf((r.comptes?.mairie?.investissement_camions_decides_fcfa || 0) / 1e6)} M FCFA, compté dans le budget consommé.</p>` : '<p>La mairie n\'a eu aucun achat à décider : le stock de dépotoirs n\'a pas grossi.</p>') : ''}
    ${r.options.agents_individuels ? `<p>Jusqu'à <b>${nf(pannes)}</b> tricycle(s) en panne le même jour.</p>` : ''}</div>`;
};

export async function render(racine) {
  racine.innerHTML = `${sousNav(SIMULATION, 'scenarios')}<h2>Scénarios et simulation</h2><p class="mut">Changez les curseurs, puis comparez à la situation de référence. Résultats de simulation sur données de démonstration.</p>
  <form id="f" onsubmit="return false">${CURS.map(([k, t, a, b, s]) => `<div class="curseur"><label for="c-${k}">${t} : <output id="o-${k}"></output></label><input type="range" id="c-${k}" min="${a}" max="${b}" step="${s}"></div>`).join('')}
  <div class="choix"><label><input type="checkbox" id="c-pluies"> Saison des pluies (pistes coupées, zones inondables)</label></div>
  <fieldset><legend>Comportement des acteurs dans la simulation</legend>
    <div class="choix"><label><input type="checkbox" id="c-ind"> Acteurs individuels : chaque tricycle a sa capacité et tombe en panne, chaque agent de la brigade peut être absent</label></div>
    <div class="choix"><label><input type="checkbox" id="c-mairie"> La mairie décide : elle achète des camions quand le stock de dépotoirs grossit (budget limité)</label></div>
    <p class="petit mut">Sans ces options, les tricycles forment un groupe par secteur et la mairie applique le plan sans décider. Les résultats du rapport sont calculés sans elles.</p></fieldset>
  <div class="choix" style="margin-top:8px"><button type="button" class="primaire" id="b-appl">Appliquer et recalculer le plan</button><button type="button" class="primaire" id="b-sim">Lancer la simulation (90 jours)</button><button type="button" class="secondaire" id="b-garder">Garder ce scénario pour comparer</button><button type="button" class="secondaire" id="b-ref">↺ Situation de référence</button></div></form>
  <div id="kpi"></div><div id="diag"></div><div id="graphes" aria-live="polite"></div>
  <h3>Comparateur de scénarios</h3><div id="comp"></div>`;
  let vivant = true; const ok = () => vivant && $('#kpi');
  let sc;
  try { sc = lireScenario(await get('/api/scenario')); } catch (e) { toast(erreurTexte(e)); sc = {}; }
  if (!ok()) return;
  const defaut = { population: commune().population, taux_abonnement: 0.437, camions: commune().camions, frequence: 1, budget: commune().budget_pr_fcfa, taux_tri: 0 };
  const poser = () => { CURS.forEach(([k, , , , , f]) => { const i = $('#c-' + k); i.value = sc[k] ?? defaut[k]; const o = $('#o-' + k); o.textContent = f(+i.value); i.oninput = () => { sc[k] = +i.value; o.textContent = f(+i.value); }; }); $('#c-pluies').checked = !!sc.saison_pluies; $('#c-ind').checked = !!sc.agents_individuels; $('#c-mairie').checked = !!sc.mairie_decisionnelle; };
  poser(); $('#c-pluies').onchange = (e) => (sc.saison_pluies = e.target.checked);
  const lire = () => { const o = {}; CURS.forEach(([k]) => (o[k] = +$('#c-' + k).value)); o.saison_pluies = $('#c-pluies').checked; o.agents_individuels = $('#c-ind').checked; o.mairie_decisionnelle = $('#c-mairie').checked; return o; };
  const dessiner = (ref, cur) => {
    const ks = Object.keys(ref).filter((k) => k !== 'jour' && Array.isArray(ref[k]) && LIB[k]);
    $('#graphes').innerHTML = ks.map((k) => { const [n, u] = LIB[k]; const f = k === 'couverture' ? 100 : 1;
      return courbes({ titre: `${n} : référence et scénario`, x: ref.jour, unite: u, series: [{ nom: 'Référence (avant)', data: ref[k].map((v) => v * f), pointille: true, couleur: '#666' }, { nom: 'Scénario (après)', data: (cur[k] || []).map((v) => v * f), couleur: COULEURS[0] }] }); }).join('');
  };
  $('#b-appl').onclick = async (e) => {
    e.target.disabled = true;
    try { const avant = lirePlan(await get('/api/plan')).kpi; await put('/api/scenario', ecrireScenario({ ...sc, ...lire() })); const p = lirePlan(await post('/api/plan/recalculer')); if (ok()) $('#kpi').innerHTML = '<h3>Effet sur le plan</h3>' + kpiHtml(p.kpi, avant); toast('Scénario appliqué.'); }
    catch (er) { toast(erreurTexte(er)); if (ok()) $('#kpi').innerHTML = `<p class="alerte err">${esc(erreurTexte(er))}</p>`; } e.target.disabled = false;
  };
  $('#b-sim').onclick = async (e) => {
    e.target.disabled = true; $('#graphes').innerHTML = '<p class="mut">Simulation en cours…</p>'; $('#diag').innerHTML = '';
    try {
      const r = await post('/api/simulation/run', { jours: 90, scenario: ecrireScenario({ ...sc, ...lire() }) }, 300000);   // 90 jours : jusqu'à quelques minutes sur un petit serveur
      const cur = lireSeries(r); let ref = cur, diag = r.diagnostic;
      try { const c = await get('/api/simulation/comparaison'); ref = lireSeries(c.reference || c); diag = diag || c.diagnostic; } catch (er) {}
      if (!ok()) return;
      dessiner(ref, cur);
      $('#diag').innerHTML = diagnosticHtml(diag, cur) + acteursHtml(r);
    } catch (er) { if (ok()) $('#graphes').innerHTML = `<p class="alerte err">${esc(erreurTexte(er))}</p>`; } e.target.disabled = false;
  };
  $('#b-ref').onclick = async (e) => {
    e.target.disabled = true;
    try { await reinitialiserScenario(); sc = lireScenario(await get('/api/scenario')); if (ok()) poser(); toast('Situation de référence rétablie.'); } catch (er) { toast(erreurTexte(er)); }
    e.target.disabled = false;
  };
  const liste = async () => {
    const l = (await kvGet('scenarios')) || []; if (!ok()) return;
    $('#comp').innerHTML = l.length ? `<div class="defile"><table><tr><th>Scénario</th><th>Camions</th><th>Abonnés</th><th>Budget</th>${KPI_DEFS.map((d) => `<th>${esc(d[1])}</th>`).join('')}</tr>${l.map((s) => `<tr><td>${esc(s.nom)}</td><td>${s.p.camions}</td><td>${nf(s.p.taux_abonnement * 100)} %</td><td>${nf(s.p.budget / 1e6)} M</td>${KPI_DEFS.map((d) => `<td>${nf(s.kpi?.[d[0]], d[3])}</td>`).join('')}</tr>`).join('')}</table></div><button class="secondaire" id="b-vider">Effacer</button>` : '<p class="mut">Aucun scénario gardé. Appliquez un scénario puis « Garder ».</p>';
    $('#b-vider')?.addEventListener('click', async () => { await kvSet('scenarios', []); liste(); });
  };
  $('#b-garder').onclick = async () => {
    try { const p = lirePlan(await get('/api/plan')); const l = (await kvGet('scenarios')) || []; l.push({ nom: 'Scénario ' + (l.length + 1), p: lire(), kpi: p.kpi }); await kvSet('scenarios', l.slice(-6)); toast('Scénario gardé.'); liste(); } catch (e) { toast(erreurTexte(e)); }
  };
  liste();
  return () => { vivant = false; };
}
