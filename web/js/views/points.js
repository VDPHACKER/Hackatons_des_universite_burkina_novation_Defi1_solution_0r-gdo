// Programme de fidélité du citoyen : points, badges, règles et défi de la commune. Tout reste sur le téléphone (aucun compte).
import { $, esc, nf, erreurTexte } from '../util.js';
import { get } from '../api.js';
import { bilan, verifierChangements, PLAFOND_PAR_JOUR, POINTS_TAILLE, POINTS_CONFIRMATION, JOURS_MEME_LIEU, BADGES } from '../fidelite.js';
import { dateFr } from '../util.js';
import { icone, symbole } from '../icones.js';

export async function render(racine) {
  racine.innerHTML = `<h2>Mes points et badges</h2>
  <div id="score" class="carte score-fidelite" aria-live="polite"><p class="mut">Chargement…</p></div>
  <h3>Mes badges</h3><ul class="badges" id="badges"></ul>
  <details class="pan" open><summary>Comment gagner des points</summary>
    <ol class="regles">
      <li>${icone('coche', 18)} <span>Les points arrivent <b>quand le tas est vérifié</b> (photo plausible, confirmation d'une autre personne ou passage d'un agent). Un envoi seul ne rapporte rien.</span></li>
      <li>${icone('camion', 18)} <span>Selon la taille : petit tas (une brouette) <b>${POINTS_TAILLE.petit}</b>, moyen <b>${POINTS_TAILLE.moyen}</b>, grand <b>${POINTS_TAILLE.grand}</b>, très grand <b>${POINTS_TAILLE.tres_grand}</b> points.</span></li>
      <li>${icone('carte', 18)} <span>Lieu déjà répertorié (dépotoir connu tout près) : <b>${POINTS_CONFIRMATION} points</b>, car votre signalement confirme celui des autres.</span></li>
      <li>${icone('sablier', 18)} <span>Le même lieu signalé de nouveau par vous en moins de ${JOURS_MEME_LIEU} jours ne rapporte rien ; au plus ${PLAFOND_PAR_JOUR} signalements récompensés par jour.</span></li>
      <li>${icone('licence', 18)} <span>Les points restent sur ce téléphone : pas de compte, pas de nom. Ils encouragent, ils ne donnent droit à aucune somme d'argent.</span></li>
    </ol>
  </details>
  <div class="pan"><h3>Mes signalements et leurs points</h3><div id="detail"></div></div>
  <div class="pan"><h3>Défi de la commune</h3><div id="defi"><p class="mut">Chargement…</p></div></div>
  <p><a class="btn primaire" href="#/signaler">${icone('camera', 18)} Signaler un tas</a> <a class="btn" href="#/suivi">${icone('suivi', 18)} Suivre mes signalements</a></p>`;
  let vivant = true;
  const ok = (s) => vivant && $(s);

  const dessiner = async () => {
    const m = await bilan();
    if (!ok('#score')) return;
    const prochain = BADGES.find((b) => !b.ok(m));
    $('#score').innerHTML = `<div class="score-ligne"><span class="score-ico" aria-hidden="true">${icone('points', 30)}</span>
        <div><b class="gros-chiffre">${nf(m.points)}</b> <span>point(s)</span><br><small class="mut">${nf(m.envoyes)} envoyé(s) · ${nf(m.verifies)} vérifié(s) · ${nf(m.aConfirmer)} à confirmer</small></div></div>
      ${prochain ? `<p class="petit">Prochain badge : <b>${esc(prochain.titre)}</b> (${esc(prochain.texte)})</p>` : '<p class="petit"><b>Tous les badges sont obtenus.</b> Merci pour votre quartier.</p>'}
      ${m.plafondAtteint ? `<p class="petit mut">Certains jours dépassent ${PLAFOND_PAR_JOUR} signalements vérifiés : les suivants ne rapportent pas de points ce jour-là.</p>` : ''}`;
    $('#detail').innerHTML = m.detail.length ? `<ul class="detail-points">${m.detail.map((r) => `<li><b>${r.points ? '+' + nf(r.points) : '0'}</b><span>${esc(r.code_suivi)} · ${esc(dateFr(r.date))}<br><small class="mut">${esc(r.raison)}</small></span></li>`).join('')}</ul>` : '<p class="mut">Aucun signalement envoyé depuis ce téléphone.</p>';
    $('#badges').innerHTML = m.badges.map((b) => `<li class="${b.obtenu ? 'obtenu' : ''}"><span class="medaille" aria-hidden="true">${b.obtenu ? symbole('verifie', 22) : icone('sablier', 22)}</span><span><b>${esc(b.titre)}</b><small>${esc(b.texte)}</small><small class="etat">${b.obtenu ? 'Obtenu' : 'À gagner'}</small></span></li>`).join('');
  };
  const defi = async () => {
    try {
      const d = await get('/api/public/defi');
      if (!ok('#defi')) return;
      const pc = Math.min(100, Math.round(d.verifies / d.objectif * 100));
      $('#defi').innerHTML = `<p>${nf(d.verifies)} dépotoir(s) vérifié(s) ces ${d.jours} derniers jours, pour un objectif de ${nf(d.objectif)}.</p>
        <div class="jauge" role="progressbar" aria-valuemin="0" aria-valuemax="${d.objectif}" aria-valuenow="${Math.min(d.verifies, d.objectif)}" aria-label="Progression du défi de la commune"><span style="width:${pc}%"></span></div>
        <p class="petit mut">${d.atteint ? 'Objectif atteint, bravo à toutes les personnes qui signalent.' : 'Chaque signalement vérifié compte pour toute la commune. Aucun classement : ni de personnes, ni de quartiers.'}</p>`;
    } catch (e) { if (ok('#defi')) $('#defi').innerHTML = `<p class="mut">${esc(e.status ? erreurTexte(e) : 'Le défi s\'affichera quand le réseau sera disponible.')}</p>`; }
  };
  await dessiner(); defi();
  verifierChangements().then(() => vivant && dessiner()).catch(() => {});        // statuts à jour : les points suivent
  return () => { vivant = false; };
}
