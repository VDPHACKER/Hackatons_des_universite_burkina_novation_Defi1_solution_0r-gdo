// Synchronisation de la file hors ligne vers POST /api/signalements.
// RÈGLE : un signalement ne quitte JAMAIS la file sur une erreur technique (réseau, 422, 5xx).
// Seule une vraie réponse de vérification (avec un statut) lui donne un statut et le sort de la file.
import { qAll, qDel, qPut, qCount, kvGet, kvSet } from './db.js';
import { post } from './api.js';
import { erreurTexte } from './util.js';

const STATUTS_OK = ['verifie', 'a_confirmer', 'rejete'];
const AVEC_VERDICT = (r) => r && STATUTS_OK.includes(r.statut);

// Format accepté par le serveur (SignalementEntree) : nature en chaîne, caniveau booléen ou null, accessibilite, horodatage.
export function versCorps(r, photos = [], audio = undefined) {
  return {
    lat: r.lat, lon: r.lon, taille: r.taille,
    nature: Array.isArray(r.nature) ? r.nature.join(',') : r.nature || null,
    caniveau: r.caniveau === 'oui' ? true : r.caniveau === 'non' ? false : null,
    accessibilite: { facile: 'camion', difficile: 'tricycle', non: 'difficile' }[r.accessible] || r.accessible || null,
    appareil: r.appareil, horodatage: r.date_client || new Date().toISOString(),
    precision_m: r.precision_m ?? undefined, sans_photo: !!r.sans_photo, exif: r.exif && r.exif.length ? r.exif : undefined,
    photos, audio, synthetique: false, cle_client: r.cle || undefined,
  };
}
// Délai d'envoi adapté au poids : sur un réseau mobile lent (≈ 100 Ko/s montants), deux photos peuvent prendre une vingtaine
// de secondes. Avant, 20 s fixes faisaient échouer l'envoi à chaque essai : le signalement restait « en attente » pour toujours.
export async function envoyer(rapport, photos, audio = undefined) {
  const octets = [...photos, audio || ''].reduce((s, x) => s + String(x || '').length, 0);
  const delai = 30000 + Math.round(octets / 1e6 * 20000);
  const r = await post('/api/signalements', versCorps(rapport, photos, audio), delai);
  const s = r.signalement || r;
  if (!AVEC_VERDICT(s)) throw Object.assign(new Error('Réponse du serveur sans verdict'), { status: 502 });
  return s;
}
export async function resultatsLocaux() { return (await kvGet('resultats')) || []; }
export async function garderResultat(x) { const l = await resultatsLocaux(); l.unshift(x); await kvSet('resultats', l.slice(0, 30)); }
export const enAttente = qCount;
export const fileComplete = qAll;
export function blobVersDataUrl(b) { return new Promise((res, rej) => { const f = new FileReader(); f.onload = () => res(f.result); f.onerror = rej; f.readAsDataURL(b); }); }

export const nouvelleCle = () => (crypto.randomUUID ? crypto.randomUUID() : 'c' + Date.now().toString(36) + Math.random().toString(36).slice(2));
let enCours = null;
// Un seul envoi à la fois ; un appel pendant un envoi attend sa fin (l'écran Signaler peut ainsi afficher le code de suivi).
export function synchroniser() {
  if (enCours) return enCours;
  if (!navigator.onLine) return Promise.resolve(0);
  enCours = envoyerFile().finally(() => { enCours = null; window.dispatchEvent(new Event('oregdo:sync')); });
  return enCours;
}
async function envoyerFile() {
  let n = 0;
  try {
    for (const it of await qAll()) {
      if (!it.rapport.cle) { it.rapport.cle = nouvelleCle(); await qPut(it); }       // signalement d'une ancienne version : clé ajoutée
      try {
        const photos = await Promise.all((it.photos || []).map(blobVersDataUrl));
        const res = await envoyer(it.rapport, photos, it.audio ? await blobVersDataUrl(it.audio) : undefined);
        await garderResultat({ ...res, cle: it.rapport.cle, taille: it.rapport.taille, deja: !!it.rapport.deja_repertorie, lat: it.rapport.lat, lon: it.rapport.lon, date: it.rapport.date_client, envoye: true });
        await qDel(it.qid); n++;
      } catch (e) {
        // Erreur technique : on GARDE le signalement, on note la raison et le nombre d'essais.
        await qPut({ ...it, essais: (it.essais || 0) + 1, derniere_erreur: erreurTexte(e), code: e.status ?? 0, dernier_essai: new Date().toISOString() });
        if (e.status === 0) break; // réseau coupé : inutile d'insister
      }
    }
  } finally { /* rien : l'état est remis par synchroniser() */ }
  return n;
}
