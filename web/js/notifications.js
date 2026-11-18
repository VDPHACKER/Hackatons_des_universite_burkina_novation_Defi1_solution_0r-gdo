// Centre de notifications des agents (brigade, mairie) : la cloche affiche le nombre de non lues, le panneau liste les événements.
// Les événements viennent du serveur (GET /api/notifications) : rien n'est stocké ici, donc rien à synchroniser.
import { get, post } from './api.js';
import { esc } from './util.js';
import { t } from './i18n.js';
import { icone } from './icones.js';

const ICONES = { a_verifier: 'ampoule', verifie: 'carte', disparu: 'alerte', intervention: 'liste' };
let etat = { non_lues: 0, evenements: [] };

const quand = (iso) => {
  const d = new Date(iso); if (isNaN(d)) return '';
  const min = Math.round((Date.now() - d) / 60000);
  if (min < 1) return t('notif.maintenant', 'À l\'instant');
  if (min < 60) return t('notif.minutes', 'Il y a {n} min', { n: min });
  if (min < 1440) return t('notif.heures', 'Il y a {n} h', { n: Math.round(min / 60) });
  return d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
};

function dessiner(panneau) {
  const l = etat.evenements;
  panneau.innerHTML = `<div class="notif-tete"><b>${esc(t('notif.titre', 'Notifications'))}</b>
      <button type="button" class="notif-fermer" aria-label="${esc(t('notif.fermer', 'Fermer'))}">${icone('croix', 16)}</button></div>` +
    (l.length ? `<ul class="notif-liste">${l.map((e) => `<li class="${e.non_lu ? 'non-lu' : ''}">
        <a href="${esc(e.lien || '#')}"><span class="notif-ico">${icone(ICONES[e.type] || 'cloche', 18)}</span>
        <span class="notif-texte"><b>${esc(e.titre)}</b><span>${esc(e.texte)}</span><small>${esc(quand(e.date))}</small></span></a></li>`).join('')}</ul>`
      : `<p class="notif-vide">${esc(t('notif.vide', 'Rien de nouveau pour le moment. Vous serez prévenu ici dès qu\'un signalement demande votre attention.'))}</p>`);
  panneau.querySelector('.notif-fermer').onclick = () => fermer(panneau);
  panneau.querySelectorAll('a').forEach((a) => (a.onclick = () => fermer(panneau)));
}

function fermer(panneau) {
  panneau.hidden = true;
  document.querySelector('#cloche')?.setAttribute('aria-expanded', 'false');
}

export async function rafraichir() {
  const n = document.querySelector('#cloche-n');
  try {
    etat = await get('/api/notifications');
    if (n) { n.textContent = etat.non_lues; n.hidden = !etat.non_lues; }
    const c = document.querySelector('#cloche');
    if (c) c.setAttribute('aria-label', etat.non_lues ? t('notif.n', '{n} notification(s) non lue(s)', { n: etat.non_lues }) : t('notif.aucune', 'Aucune nouvelle notification'));
  } catch (e) { /* hors ligne ou session expirée : on garde le dernier état affiché */ }
}

export function initialiser() {
  const c = document.querySelector('#cloche'), p = document.querySelector('#panneau-notif');
  if (!c || !p) return;
  c.onclick = async (e) => {
    e.preventDefault();
    if (!p.hidden) return fermer(p);
    await rafraichir(); dessiner(p); p.hidden = false; c.setAttribute('aria-expanded', 'true');
    p.querySelector('.notif-fermer')?.focus();
    if (etat.non_lues) { try { await post('/api/notifications/lues', {}); etat.non_lues = 0; const n = document.querySelector('#cloche-n'); if (n) n.hidden = true; } catch (err) { /* sera relu à la prochaine ouverture */ } }
  };
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !p.hidden) { fermer(p); c.focus(); } });
  document.addEventListener('click', (e) => { if (!p.hidden && !p.contains(e.target) && !c.contains(e.target)) fermer(p); });
}
