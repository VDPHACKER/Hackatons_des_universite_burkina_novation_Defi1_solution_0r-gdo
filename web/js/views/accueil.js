import { ecouter, esc, nf } from '../util.js';
import { menuDe, titre } from '../acces.js';
import { t } from '../i18n.js';
import { utilisateur, LIBELLE_ROLE } from '../session.js';
import { icone } from '../icones.js';
import { get } from '../api.js';
import { commune } from '../commune.js';
import { bilan } from '../fidelite.js';
import { installer, installee } from '../installer.js';

const TEXTE = "Voyez un tas d'ordures ? Signalez-le en trente secondes. La mairie vérifie, puis organise le ramassage. Un signalement concerne un tas, jamais une personne. Si vous ne savez pas lire, demandez à un pré-collecteur ou à une association de signaler pour vous.";

export async function render(racine) {
  const u = utilisateur();
  const raccourcis = u ? `<div class="carte"><h3 style="margin-top:0">Bonjour ${esc(u.nom)}</h3><p>${esc(LIBELLE_ROLE[u.role] || u.role)}${u.zone ? ' · ' + esc(u.zone) : ''}</p>
    <div class="choix">${menuDe(u.role).onglets.filter((n) => n !== 'accueil').map((n) => `<a class="btn primaire" href="#/${n}">${esc(titre(n))}</a>`).join('')}</div></div>` : '';
  racine.innerHTML = `${raccourcis}<section class="accueil" aria-labelledby="titre-accueil">
  ${t('salut', '') ? `<p class="chapeau"><b>${esc(t('salut', ''))}</b></p>` : ''}
  <div class="hero">
    <div class="hero-texte">
      <h2 id="titre-accueil" class="grand">${esc(t('accueil.titre1', "Un tas d'ordures dans votre quartier ?"))}<br>${esc(t('accueil.titre2', 'Signalez-le en 30 secondes.'))}</h2>
      <p class="chapeau">${esc(t('accueil.chapeau', "La mairie vérifie votre signalement, puis organise le ramassage. Vous signalez un tas, jamais une personne."))}</p>
      <div class="actions"><a class="btn-fort" href="#/signaler">${icone('camera', 22)} ${esc(t('accueil.signaler', 'Signaler un tas'))}</a><a class="btn" href="#/carte">${icone('carte', 20)} ${esc(t('accueil.carte', 'Voir la carte'))}</a></div>
      <p class="petit">${esc(t('accueil.deja', 'Déjà signalé ?'))} <a href="#/suivi">${esc(t('accueil.suivre', 'Suivre mon signalement'))}</a></p>
      <button type="button" class="carte carte-installer" id="carte-installer" hidden><span class="score-ico" aria-hidden="true">${icone('importer', 24)}</span><span><b>${esc(t('accueil.installer', "Installer l'application"))}</b><br><small class="mut" id="installer-aide">${esc(t('accueil.installer2', "Une icône sur l'écran d'accueil, utilisable sans réseau."))}</small></span></button>
      <a class="carte carte-fidelite" href="#/points" id="carte-points"><span class="score-ico" aria-hidden="true">${icone('points', 26)}</span>
        <span><b>${esc(t('accueil.points', 'Programme de fidélité'))}</b><br><small class="mut" id="points-resume">${esc(t('accueil.points2', 'Gagnez des points et des badges pour chaque tas vérifié.'))}</small></span></a>
    </div>
    <aside class="hero-chiffres" id="chiffres" aria-label="${esc(commune().nom)} en chiffres"><h3>${esc(commune().nom)}</h3><p class="mut petit">Chargement…</p></aside>
  </div>
  <div class="carte comment"><div class="comment-tete"><h3>${esc(t('accueil.comment', 'Comment ça marche'))}</h3>
    <button class="secondaire" id="b-ecouter" type="button" aria-label="Écouter cette page à voix haute">${icone('volume', 18)} ${esc(t('accueil.ecouter', 'Écouter'))}</button></div>
    <ol class="trois-etapes"><li><b>${esc(t('accueil.e1t', 'Vous photographiez le tas'))}</b><span>${esc(t('accueil.e1', 'Sans personnes : les visages et plaques sont masqués sur votre téléphone, puis vous envoyez.'))}</span></li>
    <li><b>${esc(t('accueil.e2t', 'Huit contrôles'))}</b><span>${esc(t('accueil.e2', 'Ils vérifient que le signalement est vrai : lieu, doublons, photo, date.'))}</span></li>
    <li><b>${esc(t('accueil.e3t', 'La mairie planifie'))}</b><span>${esc(t('accueil.e3', 'Les tas vérifiés entrent dans le plan de ramassage de la commune.'))}</span></li></ol>
    <p class="petit mut">${esc(t('accueil.horsligne', 'Sans réseau, le signalement reste sur votre téléphone et part dès le retour de la connexion.'))} <a href="#/confidentialite">${esc(t('accueil.donnees', 'Quelles données sont gardées ?'))}</a></p>
    <p class="petit mut">${esc(t('accueil.note', "La lecture à voix haute n'existe qu'en français. Si vous lisez peu, vous pouvez laisser un message vocal dans votre langue (français, mooré ou dioula) : un agent l'écoutera. Un relais (pré-collecteur, association de quartier) peut aussi signaler avec vous."))}</p></div>
  </section>`;
  if (u) racine.querySelectorAll('.hero-texte, .comment').forEach((e) => e.remove());      // un agent connecté n'a pas besoin du message d'appel aux citoyens
  const bouton = document.getElementById('b-ecouter'); if (bouton) bouton.onclick = () => ecouter(TEXTE);
  const ci = document.getElementById('carte-installer');
  if (ci && !installee()) { ci.hidden = false; ci.onclick = async () => { const m = await installer(); if (m) document.getElementById('installer-aide').textContent = m; }; }
  bilan().then((m) => { const z = document.getElementById('points-resume'); if (z && m.envoyes) z.textContent = `${nf(m.points)} point(s) · ${m.badges.filter((b) => b.obtenu).length} badge(s) sur ${m.badges.length}. Voir le programme.`; }).catch(() => {});
  // La commune en chiffres : données réelles de l'API publique (aucune valeur inventée).
  try {
    const [dep, plan] = await Promise.all([get('/api/public/depotoirs'), get('/api/plan')]);
    const z = document.getElementById('chiffres'); if (!z) return;
    const k = plan.kpi || {}, nb = ((dep && dep.features) || []).length, couv = k.couverture_population != null ? k.couverture_population : k.taux_couverture_production;
    z.innerHTML = `<h3>${esc(commune().nom)} aujourd'hui</h3>
      <div class="chiffre"><b>${nf(nb)}</b><span>dépotoirs confirmés sur la carte</span></div>
      <div class="chiffre"><b>${nf(k.nb_pr)}</b><span>points de regroupement où déposer ses déchets</span></div>
      <div class="chiffre"><b>${couv != null ? nf(couv * 100, 0) + ' %' : '–'}</b><span>des habitants ont un point de regroupement à portée</span></div>`;
  } catch (e) { const z = document.getElementById('chiffres'); if (z) z.hidden = true; }
}
