import { $, esc, nf, toast, fc, erreurTexte } from '../util.js';
import { get, post, lirePlan } from '../api.js';
import { kpiHtml } from '../kpi.js';
import * as M from '../map.js';
import { sousNav, PLANS } from '../sousnav.js';

const COUL = ['#d1007a', '#0057c8', '#c46a00', '#6b2fb3', '#00776e'];
function parCamion(feats) {
  const m = new Map();
  feats.forEach((f) => { const p = f.properties, k = p.camion ?? '?'; const o = m.get(k) || { camion: k, km: 0, pr: 0, kg: 0, voyages: 0 };
    o.km += +p.distance_km || 0; o.pr += p.arrets ? p.arrets.length : +p.nb_pr || 0; o.kg += +p.charge_kg || 0; o.voyages++; m.set(k, o); });
  return [...m.values()].sort((a, b) => b.kg - a.kg);
}
const ligne = (o) => `<tr><td><b style="color:${COUL[(+o.camion || 0) % 5]}">● Camion ${esc(typeof o.camion === 'number' ? o.camion + 1 : o.camion)}</b></td><td>${nf(o.voyages)}</td><td>${nf(o.pr)}</td><td>${nf(o.km, 1)} km</td><td>${nf(o.kg)} kg</td></tr>`;

export async function render(racine) {
  racine.innerHTML = `${sousNav(PLANS, 'plan')}<h2>Plan de gestion</h2>
  <div class="alerte"><b>Plan cible, pas la situation actuelle.</b> Ce que les camions et les points de regroupement pourraient faire si les dépotoirs vérifiés étaient desservis. Résultat de simulation sur données de démonstration : à ne pas citer comme un fait.</div>
  <p class="mut">Seuls les dépotoirs <b>vérifiés</b> entrent dans le plan.</p>
  <button class="primaire" id="recalc">Recalculer le plan</button> <span id="temps" class="mut" role="status"></span>
  <div id="kpi"></div>
  <div class="carte-zone" style="flex:none;height:320px;margin-top:10px"><div class="cible" id="cible-carte"></div></div>
  <h3>Tournées par camion</h3><div id="tournees"></div>
  <h3>Points de regroupement (PR) retenus</h3><div id="pr"></div>
  <h3>Où installer de nouveaux points ?</h3><div id="sugg"></div>`;
  let vivant = true; const ok = () => vivant && $('#kpi');
  await M.montrer($('#cible-carte'));
  M.visible(['sig', 'dep', 'avant'], false); M.visible(['pr', 'tournees', 'sites'], true);
  const afficher = (p, ms) => {
    if (!ok()) return;
    $('#kpi').innerHTML = kpiHtml(p.kpi) + '<p class="petit mut">Simulation sur une journée type, données synthétiques.</p>';
    $('#temps').textContent = p.temps_s != null || ms != null ? `Calculé en ${nf(p.temps_s ?? ms / 1000, 2)} s` : '';
    M.donnees('pr', p.pr); M.donnees('tournees', p.tournees);
    const t = parCamion(fc(p.tournees).features);
    $('#tournees').innerHTML = t.length ? `<p>${t.length} camions, triés par charge.</p><div class="defile"><table><tr><th>Camion</th><th>Voyages</th><th>PR</th><th>Distance</th><th>Charge</th></tr>${t.slice(0, 8).map(ligne).join('')}</table></div>${t.length > 8 ? `<details><summary>Voir les ${t.length - 8} autres camions</summary><div class="defile"><table>${t.slice(8).map(ligne).join('')}</table></div></details>` : ''}` : '<p class="mut">Aucune tournée.</p>';
    const pr = fc(p.pr).features;
    $('#pr').innerHTML = pr.length ? `<p>${pr.length} PR retenus.</p><details><summary>Voir la liste</summary><ul>${pr.slice(0, 60).map((f) => `<li>${esc(f.properties.id)}${f.properties.secteur ? ' · secteur ' + esc(f.properties.secteur) : ''}${f.properties.cout_fcfa ? ' · ' + nf(f.properties.cout_fcfa) + ' FCFA' : ''}</li>`).join('')}</ul></details>` : '<p class="mut">Aucun PR retenu.</p>';
  };
  const charger = async () => {
    try { const p = lirePlan(await get('/api/plan')); afficher(p); } catch (e) { toast(erreurTexte(e)); }
    try {
      const s = fc(await get('/api/suggestions/emplacements')); M.donnees('sites', s);
      if (ok()) $('#sugg').innerHTML = s.features.slice(0, 6).map((f) => { const p = f.properties; return `<div class="carte"><b>${p.type === 'decharge' ? 'Décharge / transfert' : 'Point de regroupement'} ${esc(p.id)}</b>${p.rang ? ' · n° ' + esc(p.rang) : ''}<br>${esc(p.justification || (p.justifications || []).join(' ; ') || 'Justification non fournie.')}</div>`; }).join('') || '<p class="mut">Pas de suggestion.</p>';
    } catch (e) { if (ok()) $('#sugg').innerHTML = `<p class="mut">${esc(erreurTexte(e))}</p>`; }
  };
  $('#recalc').onclick = async (e) => {
    e.target.disabled = true; const t0 = performance.now();
    try { const p = lirePlan(await post('/api/plan/recalculer', {}, 120000)); afficher(p, performance.now() - t0); toast('Plan recalculé.'); }
    catch (er) { toast(erreurTexte(er)); if (ok()) $('#temps').textContent = 'Recalcul impossible : ' + erreurTexte(er); }
    e.target.disabled = false;
  };
  charger();
  return () => { vivant = false; };
}
