// Session de l'utilisateur connecté : jeton signé (Authorization: Bearer) + identité, gardés sur cet appareil.
// Le serveur reste la seule autorité : ici on ne fait que choisir quoi afficher. Chaque route /api vérifie le rôle.
import { kvEffacerPrive } from './db.js';

const CLE = 'oregdo.session';

function lire() {
  try {
    const s = JSON.parse(localStorage.getItem(CLE) || 'null');
    if (!s || !s.jeton || !s.utilisateur) return null;
    if (s.expire_le && Date.parse(s.expire_le) < Date.now()) { localStorage.removeItem(CLE); return null; }
    return s;
  } catch (e) { return null; }
}
let courante = lire();

export const jeton = () => courante?.jeton || '';
export const utilisateur = () => courante?.utilisateur || null;
export const role = () => courante?.utilisateur?.role || null;
export const connecte = () => !!courante;

export function ouvrir(reponse) {
  courante = { jeton: reponse.jeton, expire_le: reponse.expire_le, utilisateur: reponse.utilisateur };
  try { localStorage.setItem(CLE, JSON.stringify(courante)); } catch (e) { /* stockage bloqué : la session vaut pour cet onglet */ }
  window.dispatchEvent(new Event('oregdo:session'));
}

export function fermer() {
  courante = null;
  kvEffacerPrive();
  try { localStorage.removeItem(CLE); } catch (e) { /* rien à faire */ }
  window.dispatchEvent(new Event('oregdo:session'));
}

/** `roles` vide ou absent : écran public. L'administrateur passe partout (comme sur le serveur). */
export function autorise(roles) {
  if (!roles || !roles.length) return true;
  const r = role();
  return !!r && (r === 'admin' || roles.includes(r));
}

export const LIBELLE_ROLE = { precollecteur: 'Pré-collecteur', brigade: 'Brigade Laabal', mairie: 'Mairie', admin: 'Administration et jury' };
