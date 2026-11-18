import { $, $$, esc, badge, dateFr, erreurTexte, nf } from '../util.js';
import { get } from '../api.js';
import { resultatsLocaux } from '../sync.js';
import { bilan, verifierChangements, effacerAlertes, alertesSuivi, libelleStatut } from '../fidelite.js';
import { icone } from '../icones.js';

const chrono = (h) => `<ol class="chrono">${(h || []).map((e) => `<li class="${esc(e.statut)}"><b>${esc(libelleStatut(e.statut))}</b><span>${esc(e.texte)}</span><small>${esc(dateFr(e.date))}</small></li>`).join('')}</ol>`;

export async function render(racine, params) {
  racine.innerHTML = `<h2>Suivre mon signalement</h2>
  <p class="mut">Entrez le code reçu à l'envoi (ex. <b>PJEAJAK5WL</b>). Pas de compte, pas de nom : le code suffit, et il ne révèle ni votre position ni votre identité.</p>
  <form id="f" novalidate class="ligne-code">
    <label for="code">Code de suivi</label>
    <div class="champ-bouton"><input id="code" autocomplete="off" autocapitalize="characters" spellcheck="false" maxlength="40" value="${esc(params.get('code') || '')}"><button class="primaire" type="submit">Voir l'état</button></div>
  </form>
  <div id="res" aria-live="polite"></div>
  <div class="pan" style="margin-top:14px"><h3>Mes signalements (sur ce téléphone)</h3><div id="mes"></div></div>
  <a class="carte lien-points" href="#/points" id="badges"></a>`;
  let vivant = true;
  const ok = (s) => vivant && $(s);
  const voir = async (code) => {
    const z = $('#res'); if (!z) return;
    code = String(code || '').trim();
    if (!code) { z.innerHTML = '<p class="alerte err" role="alert">Saisissez un code de suivi.</p>'; return; }
    z.innerHTML = '<p class="mut">Recherche…</p>';
    try {
      const s = await get('/api/suivi/' + encodeURIComponent(code));
      if (!ok('#res')) return;
      $('#res').innerHTML = `<div class="carte"><h3>${esc(s.code_suivi)} ${badge(s.statut)}</h3><p>${esc(s.message)}</p>
        ${s.historique && s.historique.length ? chrono(s.historique) : ''}
        <p class="petit mut">Reçu le ${esc(dateFr(s.recu_le))}${s.tas_confirme ? ' · le tas fait partie d\'un dépotoir vérifié, il entre dans le plan de ramassage' : ''}.</p></div>`;
    } catch (e) {
      if (ok('#res')) $('#res').innerHTML = `<p class="alerte err" role="alert">${esc(e.status === 404 ? "Aucun signalement ne correspond à ce code. Vérifiez qu'il est bien recopié." : erreurTexte(e))}</p>`;
    }
  };
  $('#f').onsubmit = (e) => { e.preventDefault(); voir($('#code').value); };

  const dessinerMes = async () => {
    const [locaux, nouveaux] = await Promise.all([resultatsLocaux().then((l) => l.filter((r) => r.code_suivi)), alertesSuivi()]);
    if (!ok('#mes')) return;
    $('#mes').innerHTML = locaux.length
      ? locaux.slice(0, 10).map((r) => `<div class="ligne-signalement${nouveaux.includes(r.code_suivi) ? ' nouveau' : ''}"><div><b>${esc(r.code_suivi)}</b> ${badge(r.statut)}${nouveaux.includes(r.code_suivi) ? ' <span class="pastille-nouveau">mis à jour</span>' : ''}<br><small class="mut">${esc(dateFr(r.date))}</small></div>
        <button class="secondaire" data-code="${esc(r.code_suivi)}">Voir l'état</button></div>`).join('')
      : '<p class="mut">Aucun code enregistré sur ce téléphone. Vos signalements apparaîtront ici avec leur état.</p>';
    $$('[data-code]').forEach((b) => (b.onclick = () => { $('#code').value = b.dataset.code; voir(b.dataset.code); window.scrollTo({ top: 0, behavior: 'smooth' }); }));
  };
  const dessinerBadges = async () => {
    const m = await bilan();
    if (!ok('#badges')) return;
    $('#badges').innerHTML = `<span class="score-ico" aria-hidden="true">${icone('points', 26)}</span>
      <span><b>${nf(m.points)} point(s)</b> · ${m.badges.filter((b) => b.obtenu).length} badge(s) sur ${m.badges.length}<br><small class="mut">Programme de fidélité : voir mes badges et comment gagner des points</small></span>`;
  };

  await dessinerMes(); dessinerBadges();
  // Ouvrir cet écran = avoir lu les mises à jour ; on interroge d'abord le serveur pour être à jour.
  verifierChangements().then(async () => { if (!vivant) return; await dessinerMes(); await dessinerBadges(); await effacerAlertes(); window.dispatchEvent(new Event('oregdo:suivi')); }).catch(() => {});
  if (params.get('code')) voir(params.get('code'));
  return () => { vivant = false; };
}
