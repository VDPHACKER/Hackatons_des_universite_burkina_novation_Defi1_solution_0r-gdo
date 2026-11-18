import './reprise.js';                        // d'abord : reprend les réglages d'une version précédente
import { $, $$, ago, toast, esc } from './util.js';
import { etat, surEtat, post, get } from './api.js';
import { synchroniser } from './sync.js';
import { ECRANS, menuDe, titre, titreCourt, titreLateral, destine } from './acces.js';
import { icone } from './icones.js';
import { LANGUES, initLangue, choisir, langue, statut, t } from './i18n.js';
import { chargerCommune, commune } from './commune.js';
import { verifierChangements, alertesSuivi, libelleStatut } from './fidelite.js';
import { installer, installee, surChangement } from './installer.js';
import { preparationAutomatique } from './horsligne.js';
import { initialiser as initNotifications, rafraichir as rafraichirNotifications } from './notifications.js';
import { role, utilisateur, connecte, autorise, fermer, LIBELLE_ROLE } from './session.js';

const PLEIN = new Set(['carte']);
const LARGES = new Set(['mairie', 'arrondissement', 'scenarios', 'plan', 'rapports']);   // écrans qui profitent de toute la largeur
let nettoyage = null, nav = 0;

function themeInit() {
  let t = null; try { t = localStorage.getItem('oregdo.theme'); } catch (e) {}
  if (t) document.documentElement.dataset.theme = t;
  $('#btn-theme').onclick = () => {
    const sombre = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() !== '#fff';
    const n = sombre ? 'light' : 'dark'; document.documentElement.dataset.theme = n;
    try { localStorage.setItem('oregdo.theme', n); } catch (e) {}
  };
  let eco = false; try { eco = localStorage.getItem('oregdo.eco') === '1'; } catch (e) {}
  const maj = () => { document.body.classList.toggle('eco', eco); $('#btn-eco').setAttribute('aria-pressed', eco); $('#btn-eco').textContent = eco ? 'Éco activé' : 'Éco'; };
  maj();
  $('#btn-eco').onclick = () => { eco = !eco; try { localStorage.setItem('oregdo.eco', eco ? '1' : '0'); } catch (e) {} maj(); toast(eco ? 'Mode économie de données : pas de fond OSM, photos plus légères, routes masquées (au prochain chargement).' : 'Mode économie désactivé.'); };
}

function puces() {
  const maj = () => {
    const r = $('#puce-reseau'); r.textContent = etat.online ? 'En ligne' : 'Hors ligne'; r.classList.toggle('hors', !etat.online);
    const bh = $('#bandeau-hors-ligne'); if (bh) bh.hidden = etat.online;
    // Bandeau tant que les données affichées sont synthétiques : on ne doit pas les prendre pour la réalité.
    $('#bandeau-synth').hidden = etat.synthetique !== true;
    const f = $('#puce-fraicheur'); f.textContent = etat.perime ? `Données du cache (${ago(etat.derniere)})` : 'Données : ' + ago(etat.derniere);
    f.style.fontWeight = etat.perime || (etat.derniere && Date.now() - etat.derniere > 864e5) ? '700' : '400';
  };
  surEtat(maj); maj(); setInterval(maj, 30000);
  window.addEventListener('online', () => synchroniser().then((n) => { if (n) toast(`${n} signalement(s) envoyé(s).`); }));
}

// Petit menu déroulant de l'en-tête (langue, compte) : un bouton, une liste ; se ferme au clic ailleurs ou avec Échap.
function deroulant(zone, boutonHtml, libelle, itemsHtml) {
  zone.innerHTML = `<button type="button" class="puce bouton dd-bouton" aria-haspopup="true" aria-expanded="false" aria-label="${esc(libelle)}">${boutonHtml}</button><div class="dd-liste" hidden>${itemsHtml}</div>`;
  const b = $('.dd-bouton', zone), l = $('.dd-liste', zone);
  const basculer = (ouvrir) => { l.hidden = !ouvrir; b.setAttribute('aria-expanded', String(ouvrir)); };
  b.onclick = (e) => { e.stopPropagation(); $$('.dd-liste').forEach((x) => { if (x !== l) { x.hidden = true; x.previousElementSibling?.setAttribute('aria-expanded', 'false'); } }); basculer(l.hidden); };
  l.onclick = (e) => { if (e.target.closest('a,button')) basculer(false); };
  return { bouton: b, liste: l };
}
document.addEventListener('click', (e) => { if (!e.target.closest('.menu-deroulant')) $$('.dd-liste').forEach((l) => { l.hidden = true; l.previousElementSibling?.setAttribute('aria-expanded', 'false'); }); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') $$('.dd-liste').forEach((l) => { if (!l.hidden) { l.hidden = true; l.previousElementSibling?.focus(); } }); });

// Barre du haut : un seul bouton « compte ». Non connecté : il mène à la connexion. Connecté : nom, rôle, paramètres, déconnexion.
function barreUtilisateur() {
  const u = utilisateur(), z = $('#zone-utilisateur');
  if (!u) {
    z.innerHTML = `<a class="puce bouton" href="#/connexion" id="btn-entrer" aria-label="Connexion des agents">${icone('personne', 20)}<span class="txt-large">Connexion</span></a>`;
    return;
  }
  const initiales = esc((u.nom || '?').trim().split(/\s+/).map((x) => x[0]).slice(0, 2).join('').toUpperCase());
  deroulant(z, `<span class="avatar" aria-hidden="true">${initiales}</span><span class="txt-large">${esc(u.nom)}</span>`, `Mon compte : ${u.nom}`,
    `<p class="dd-titre"><b>${esc(u.nom)}</b><small>${esc(LIBELLE_ROLE[u.role] || u.role)} · ${esc(u.identifiant)}</small></p>
     <a href="#/parametres">${icone('parametres', 18)} ${esc(t('nav.parametres', 'Paramètres'))}</a>
     <button type="button" id="btn-sortir">${icone('sortie', 18)} ${esc(t('sortir', 'Déconnexion'))}</button>`);
  $('#btn-sortir').onclick = async () => {
    try { await post('/api/auth/deconnexion'); } catch (e) { /* session déjà invalide côté serveur : on la ferme ici de toute façon */ }
    fermer(); toast('Vous êtes déconnecté.'); location.hash = '#/accueil';
  };
}

// Navigation du bas (icône + mot court) et feuille « Plus » : construites d'après le rôle. Le serveur vérifie quand même chaque route.
function menu() {
  const m = menuDe(role());
  $('#onglets').innerHTML = m.onglets.map((n) => `<a href="#/${n}">${icone(n, 22)}<b>${esc(titreCourt(n))}</b></a>`).join('') + `<button id="btn-plus" aria-expanded="false" aria-controls="plus">${icone('menu', 22)}<b>${esc(t('nav.plus', 'Plus'))}</b></button>`;
  $('#plus').innerHTML = `<h2>${esc(t('nav.plus', 'Plus'))}</h2>` + (installee() ? '' : `<button type="button" class="primaire" id="btn-installer">${icone('importer', 20)} ${esc(t('installer', "Installer l'application"))}</button><p class="petit mut" id="aide-installer" hidden></p>`) + m.plus.map((n) => `<a href="#/${n}">${icone(n, 20)} ${esc(titre(n))}</a>`).join('') + `<button id="plus-fermer" class="secondaire">${esc(t('fermer', 'Fermer'))}</button>`;
  $('#btn-installer')?.addEventListener('click', async () => { const m2 = await installer(); const z = $('#aide-installer'); if (z && m2) { z.textContent = m2; z.hidden = false; } });
  const lat = (n, cl = '') => `<a href="#/${n}" data-n="${n}"${cl}>${icone(n)}<span>${esc(titreLateral(n))}</span></a>`;
  $('#nav-lateral').innerHTML = m.onglets.map((n) => lat(n)).join('') + (m.plus.length ? '<hr class="separe">' + m.plus.map((n) => lat(n, ' class="second"')).join('') : '');
  $('#btn-plus').onclick = () => { const p = $('#plus'); p.hidden = !p.hidden; $('#btn-plus').setAttribute('aria-expanded', String(!p.hidden)); };
  $('#plus-fermer').onclick = () => ($('#plus').hidden = true);
}

function refuser(racine, nom) {
  const e = ECRANS[nom];
  if (!connecte()) {
    location.replace('#/connexion?retour=' + encodeURIComponent(nom));
    return;
  }
  racine.innerHTML = `<h2>${esc(e.titre)}</h2><div class="alerte err" role="alert"><b>Accès refusé.</b> Cet écran est réservé à : ${esc(e.roles.map((r) => LIBELLE_ROLE[r]).join(', '))}. Vous êtes connecté comme ${esc(LIBELLE_ROLE[role()] || role())}.</div><p><a class="btn" href="#/accueil">Retour à l'accueil</a></p>`;
}

async function aller() {
  const id = ++nav;
  const [, nom0 = 'accueil'] = (location.hash || '#/accueil').split('?')[0].split('/');
  const nom = ECRANS[nom0] ? nom0 : 'accueil';
  ecranCourant = nom; zoneArr();
  const ecran = ECRANS[nom];
  const racine = $('#vue');
  if (nettoyage) { try { nettoyage(); } catch (e) {} nettoyage = null; }
  window.scrollTo(0, 0);
  racine.className = PLEIN.has(nom) ? 'plein' : LARGES.has(nom) ? 'large' : '';
  const parent = { arrondissement: 'plan', jury: 'scenarios' }[nom] || nom;            // vues d'un même écran : le menu garde l'écran parent allumé
  $$('#onglets a, #nav-lateral a').forEach((a) => a.classList.toggle('actif', a.getAttribute('href') === '#/' + parent));
  $('#plus').hidden = true; $('#btn-plus')?.setAttribute('aria-expanded', 'false');
  if (!autorise(ecran.roles)) { refuser(racine, nom); return; }
  if (!destine(nom, role())) {
    racine.innerHTML = `<h2>${esc(titre(nom))}</h2><div class="alerte info" role="status">Cet écran sert aux habitants. Votre compte ${esc(LIBELLE_ROLE[role()] || role())} a ses propres outils dans le menu.
      Pour signaler en tant qu'habitant, déconnectez-vous d'abord.</div><p><a class="btn primaire" href="#/${menuDe(role()).onglets[0]}">Aller à mon espace</a></p>`;
    return;
  }
  racine.innerHTML = '<p class="mut">Chargement…</p>';
  try {
    const m = await import(`./views/${ecran.fichier}.js`);
    if (id !== nav) return;
    racine.innerHTML = '';
    const c = (await m.render(racine, new URLSearchParams((location.hash.split('?')[1]) || ''))) || null;
    if (id !== nav) { if (c) try { c(); } catch (e) {} return; }
    nettoyage = c;
  } catch (e) {
    if (id !== nav) return;
    console.error(e);
    racine.innerHTML = `<div class="alerte err"><b>Cet écran n'a pas pu s'afficher.</b><br>${esc(String(e.message || e))}<br><button class="secondaire" onclick="location.reload()">Réessayer</button></div>`;
  }
  if (id === nav) racine.focus({ preventScroll: true });
}

// Langue : choix mémorisé, dioula et mooré sont des BROUILLONS tant que des locuteurs natifs ne les ont pas validés ; le français sert de repli.
// Un seul bouton (globe + code de la langue) ouvre la liste des trois langues.
function langues() {
  const s = $('#sel-langue');
  const { liste } = deroulant(s, `${icone('langue', 20)}<span class="code-langue">${esc(langue().toUpperCase())}</span>`, `Langue : ${LANGUES[langue()]}. Changer de langue`,
    Object.entries(LANGUES).map(([c, n]) => `<button type="button" data-l="${c}" lang="${c}" aria-current="${c === langue()}">${c === langue() ? icone('coche', 18) : '<span class="ico-vide"></span>'} ${esc(n)}${c === 'fr' ? '' : ' <small>(brouillon)</small>'}</button>`).join(''));
  liste.addEventListener('click', (e) => { const b = e.target.closest('button[data-l]'); if (b && b.dataset.l !== langue()) choisir(b.dataset.l); });
  const b = $('#bandeau-langue');
  b.hidden = statut() !== 'brouillon';
  b.innerHTML = '<b>Traduction en cours de validation.</b> Les textes en dioula et en mooré sont des brouillons : en cas de doute, lisez le français. Vous pouvez aussi laisser un message vocal dans votre langue.';
}
// Suivi du citoyen : on interroge le serveur pour les signalements gardés sur ce téléphone et on prévient la personne quand l'un d'eux change.
async function pastilleSuivi() {
  const n = (await alertesSuivi()).length;
  $$('#onglets a[href="#/suivi"], #nav-lateral a[href="#/suivi"]').forEach((a) => a.classList.toggle('avec-point', n > 0));
}
async function surveillerSuivi() {
  try { for (const x of await verifierChangements()) toast(t('suivi.change', 'Votre signalement {code} est maintenant : {etat}.', { code: x.code, etat: libelleStatut(x.nouveau) })); } catch (e) { /* hors ligne : au prochain passage */ }
  pastilleSuivi();
}
let ecranCourant = 'accueil';
// Le filtre d'arrondissement ne sert que sur le tableau de bord et le plan d'un arrondissement : ailleurs, il encombre.
function zoneArr() { const z = $('#zone-arr'); if (z) z.hidden = !(['mairie', 'admin'].includes(role()) && ['mairie', 'arrondissement'].includes(ecranCourant)); }
function marque() {                         // nom de l'application et de la commune, d'après la configuration du pack
  const m = commune().marque || 'Orẽgdo';                   // le nom du produit est le même partout ; la commune s'affiche à côté
  $('#marque-a').textContent = m; $('#marque-b').textContent = '';
  $('#marque-mobile').textContent = m; $('#lieu-commune').textContent = commune().nom; $('#nom-commune').textContent = commune().nom;
  $('#pied-droit').textContent = t('pied.durable', 'Vers une ville durable à {nom}', { nom: commune().nom });
  document.title = m + ' : ' + commune().nom;
  const sc = $('#synth-commune'); if (sc) sc.textContent = commune().nom;
}

// Cloche : nombre de signalements à vérifier (agents, mairie) ; filtre d'arrondissement du tableau de bord (mairie).
async function cloche() {
  const r = role(), c = $('#cloche');
  const agent = ['brigade', 'mairie', 'admin'].includes(r);
  c.hidden = !agent; zoneArr();
  if (!agent) return;
  if (['brigade', 'mairie', 'admin'].includes(r)) await rafraichirNotifications();
}
async function filtreArrondissement() {
  const s = $('#sel-arr'); if (!s || s.dataset.pret) return; s.dataset.pret = '1';
  try {
    const l = (await get('/api/plan/arrondissements')).arrondissements.map((x) => [x.code, x.nom]).sort((a, b) => a[0].localeCompare(b[0]));
    let c = ''; try { c = localStorage.getItem('oregdo.arr') || ''; } catch (e) { /* ignoré */ }
    s.innerHTML = `<option value="">${esc(t('arr.tous', 'Tous'))}</option>` + l.map(([k, n]) => `<option value="${k}" ${k === c ? 'selected' : ''}>${esc(n)}</option>`).join('');
    s.onchange = () => { try { localStorage.setItem('oregdo.arr', s.value); } catch (e) { /* ignoré */ } window.dispatchEvent(new CustomEvent('oregdo:arr', { detail: s.value })); };
  } catch (e) { s.dataset.pret = ''; }
}
await initLangue();
await chargerCommune();
marque();
if (!window.isSecureContext) {                 // http hors localhost : GPS, micro et installation bloqués par le navigateur
  const b = document.createElement('div'); b.className = 'bandeau'; b.setAttribute('role', 'note');
  b.innerHTML = '<b>Connexion non sécurisée (http).</b> Le navigateur bloque le GPS, le micro et l\'installation de l\'application. Ouvrez l\'application par son adresse <b>https</b> (demandez-la à l\'administrateur de la plateforme).';
  $('#bandeau-langue').before(b);
}
$$('.ico-slot').forEach((e) => (e.innerHTML = icone(e.dataset.ico, 16)));
themeInit(); langues(); puces(); barreUtilisateur(); menu(); initNotifications(); pastilleSuivi();
// Connexion, déconnexion ou session expirée : on reconstruit le menu et l'écran (un écran réservé renvoie alors à la connexion).
window.addEventListener('oregdo:session', () => { barreUtilisateur(); menu(); pastilleSuivi(); cloche(); filtreArrondissement(); aller(); });
cloche(); filtreArrondissement(); setInterval(cloche, 60000);
surChangement(menu);                       // le bouton « Installer » apparaît ou disparaît selon le navigateur
window.addEventListener('hashchange', aller);
aller();
synchroniser().catch(() => {});
setInterval(() => synchroniser().catch(() => {}), 60000);
preparationAutomatique();                  // en Wi-Fi : masquage et données gardés pour l'utilisation sans réseau
setTimeout(surveillerSuivi, 4000); setInterval(surveillerSuivi, 300000);          // toutes les 5 minutes tant que l'application est ouverte
window.addEventListener('oregdo:suivi', pastilleSuivi); window.addEventListener('online', surveillerSuivi);
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js').catch(() => {});
  navigator.serviceWorker.addEventListener('message', (e) => { if (e.data === 'sync') synchroniser(); });
}
