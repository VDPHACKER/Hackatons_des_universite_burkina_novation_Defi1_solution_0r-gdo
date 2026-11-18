import { $, esc, nf, erreurTexte } from '../util.js';
import { get, lirePlan } from '../api.js';
import { kpiHtml } from '../kpi.js';

const carte = (titre, valeur, aide) => `<div class="kpi"><span>${esc(titre)}</span><b>${esc(valeur)}</b><small class="mut">${esc(aide)}</small></div>`;

export async function render(racine) {
  racine.innerHTML = `<h2>Tableau de bord de la mairie</h2>
  <div class="choix"><a class="btn primaire" href="#/plan">Plan de gestion</a><a class="btn" href="#/scenarios">Scénarios et simulation</a><a class="btn" href="#/carte">Carte</a><a class="btn" href="#/commun">Export OpenStreetMap</a></div>
  <div id="synth"></div>
  <h3>Sur le terrain</h3><div id="terrain" aria-live="polite"><p class="mut">Chargement…</p></div>
  <h3>Étalonnage sur le terrain</h3><div id="etalonnage" aria-live="polite"><p class="mut">Chargement…</p></div>
  <h3>Plan de gestion (plan cible)</h3><div id="plan"><p class="mut">Chargement…</p></div>`;
  let vivant = true;
  const ok = (id) => vivant && $(id);
  // Étalonnage : ce que les pré-collecteurs saisissent, comparé à ce que suppose le modèle. Il mesure l'écart et conseille ; il ne change aucun paramètre.
  get('/api/calibrage').then((c) => {
    if (!ok('#etalonnage')) return;
    const classe = !c.suffisant ? 'info' : Math.abs(c.ecart_pct) <= c.seuils.tolerance_pct ? '' : 'err';
    $('#etalonnage').innerHTML = `<div class="grille">${carte('Observé sur le terrain', c.kg_par_menage_observe != null ? nf(c.kg_par_menage_observe, 2) + ' kg' : '–', 'par ménage servi et par jour')}
      ${carte('Supposé par le modèle', nf(c.kg_par_menage_modele, 2) + ' kg', 'par ménage et par jour')}
      ${carte('Écart', c.ecart_pct != null ? (c.ecart_pct > 0 ? '+' : '') + nf(c.ecart_pct, 0) + ' %' : '–', `${nf(c.collectes)} collecte(s) sur ${nf(c.points)} point(s)`)}</div>
      <p class="alerte ${classe}">${esc(c.avis)}</p>`;
  }).catch((e) => { if (ok('#etalonnage')) $('#etalonnage').innerHTML = `<p class="mut">${esc(erreurTexte(e))}</p>`; });
  try {
    const k = await get('/api/mairie/kpi');
    if (ok('#terrain')) {
      const s = k.signalements, i = k.interventions, c = k.collectes;
      if (s.synthetique) $('#synth').innerHTML = '<div class="alerte"><b>Données de démonstration.</b> Une partie des signalements est synthétique : ne pas la citer comme la situation réelle.</div>';
      $('#terrain').innerHTML = `<div class="grille">
        ${carte('Signalements reçus', nf(s.total), `${nf(s.par_statut.verifie)} vérifiés · ${nf(s.par_statut.a_confirmer)} à confirmer · ${nf(s.par_statut.rejete)} rejetés`)}
        ${carte('Dépotoirs vérifiés', nf(k.depotoirs_verifies), 'Un tas = un dépotoir, même signalé par plusieurs personnes.')}
        ${carte('Sensibilisations', nf(i.sensibilisation), 'Première phase de la brigade Laabal.')}
        ${carte('Sanctions', nf(i.sanction), `${nf(i.montant_total_fcfa)} FCFA d'amendes prononcées`)}
        ${carte('Collecté par les pré-collecteurs', nf(c.kg, 0) + ' kg', `${nf(c.nb_collectes)} collecte(s) · ${nf(c.nb_menages)} ménages`)}</div>
        ${c.par_point.length ? `<details><summary>Collecte par point de regroupement</summary><div class="defile"><table><tr><th>Point</th><th>Poids</th><th>Collectes</th></tr>${c.par_point.map((p) => `<tr><td>${esc(p.point)}</td><td>${esc(nf(p.kg, 1))} kg</td><td>${esc(p.nb_collectes)}</td></tr>`).join('')}</table></div></details>` : ''}`;
    }
  } catch (e) { if (ok('#terrain')) $('#terrain').innerHTML = `<p class="alerte err" role="alert">${esc(erreurTexte(e))}</p>`; }
  try {
    const p = lirePlan(await get('/api/plan'));
    if (ok('#plan')) {
      const b = p.brut.kpi || {};
      $('#plan').innerHTML = `<p class="mut petit">Plan cible calculé pour le scénario courant (hypothèses [H] à confirmer avec la mairie). ${p.temps_s != null ? 'Calculé en ' + nf(p.temps_s, 2) + ' s.' : ''}</p>${kpiHtml(p.kpi)}
        <p>${nf(b.nb_pr)} points de regroupement · ${nf(b.camions_utilises)} camion(s) sur ${nf(b.camions_disponibles)} · ${nf(b.nb_depotoirs_verifies)} dépotoir(s) vérifié(s) à évacuer · coût complet ${nf(b.cout_par_tonne_fcfa)} FCFA la tonne.</p>`;
    }
  } catch (e) { if (ok('#plan')) $('#plan').innerHTML = `<p class="alerte err" role="alert">${esc(erreurTexte(e))}</p>`; }
  return () => { vivant = false; };
}
