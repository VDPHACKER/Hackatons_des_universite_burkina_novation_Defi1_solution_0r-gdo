// Suivi des signalements du téléphone, notification du citoyen et badges.
// Tout reste sur l'appareil : aucun compte, aucun numéro, aucune donnée personnelle envoyée. Les points ne comptent que les signalements VÉRIFIÉS
// (les contrôles du serveur font foi), avec un plafond par jour, et ne donnent aucune récompense monétaire.
import { kvGet, kvSet } from './db.js';
import { get } from './api.js';

const LIBELLES = { verifie: 'vérifié', a_confirmer: 'à confirmer sur place', rejete: 'non retenu' };
export const libelleStatut = (s) => LIBELLES[s] || s;

export const PLAFOND_PAR_JOUR = 3;            // au plus 3 signalements récompensés par jour
export const RAYON_MEME_LIEU_M = 50, JOURS_MEME_LIEU = 7;
// Points d'un signalement VÉRIFIÉ, selon la taille du tas : un petit déchet rapporte peu, un vrai dépotoir rapporte plus.
export const POINTS_TAILLE = { petit: 2, moyen: 5, grand: 10, tres_grand: 15 };
export const POINTS_CONFIRMATION = 3;          // lieu déjà répertorié : le signalement confirme un dépotoir connu
export const POINTS_DEFAUT = 5;                // taille non précisée (message vocal)
export const BADGES = [
  { id: 'premier', titre: 'Premier signalement', texte: 'Vous avez signalé un tas.', ok: (m) => m.envoyes >= 1 },
  { id: 'verifie', titre: 'Signalement vérifié', texte: 'Un de vos signalements est confirmé : il entre dans le plan de ramassage.', ok: (m) => m.verifies >= 1 },
  { id: 'oeil', titre: 'Œil du quartier', texte: '5 signalements vérifiés.', ok: (m) => m.verifies >= 5 },
  { id: 'sentinelle', titre: 'Sentinelle', texte: '10 signalements vérifiés.', ok: (m) => m.verifies >= 10 },
];
export const LIBELLE_TAILLE = { petit: 'petit tas', moyen: 'tas moyen', grand: 'grand tas', tres_grand: 'très grand tas' };

export const distanceM = (a, b) => { const r = Math.PI / 180, dLa = (b.lat - a.lat) * r, dLo = (b.lon - a.lon) * r;
  const h = Math.sin(dLa / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLo / 2) ** 2; return 12742000 * Math.asin(Math.sqrt(h)); };
export const pointsPossibles = (taille, deja) => (deja ? POINTS_CONFIRMATION : POINTS_TAILLE[taille] ?? POINTS_DEFAUT);

async function locaux() { return ((await kvGet('resultats')) || []).filter((r) => r.code_suivi); }

// Barème appliqué à chaque signalement du téléphone, du plus ancien au plus récent : il dit combien il rapporte ET pourquoi.
export function bareme(liste) {
  const parJour = {}, recompenses = [];
  return [...liste].reverse().map((r) => {
    if (r.statut !== 'verifie') return { ...r, points: 0, raison: r.statut === 'rejete' ? 'Non retenu : aucun point.' : 'En attente de vérification : les points arrivent quand le tas est confirmé.' };
    const j = String(r.date || '').slice(0, 10), t = Date.parse(r.date || '') || 0;
    const memeLieu = r.lat != null && recompenses.find((x) => distanceM(x, r) <= RAYON_MEME_LIEU_M && Math.abs(t - x.t) <= JOURS_MEME_LIEU * 864e5);
    if (memeLieu) return { ...r, points: 0, raison: `Lieu déjà signalé par vous il y a moins de ${JOURS_MEME_LIEU} jours : pas de nouveaux points.` };
    if ((parJour[j] || 0) >= PLAFOND_PAR_JOUR) return { ...r, points: 0, raison: `Plafond de ${PLAFOND_PAR_JOUR} signalements récompensés atteint ce jour-là.` };
    parJour[j] = (parJour[j] || 0) + 1;
    recompenses.push({ lat: r.lat, lon: r.lon, t });
    const p = pointsPossibles(r.taille, r.deja);
    return { ...r, points: p, raison: r.deja ? 'Confirmation d\'un dépotoir déjà répertorié.' : `Vérifié : ${LIBELLE_TAILLE[r.taille] || 'taille non précisée'}.` };
  }).reverse();
}

// Mesures et badges à partir des signalements gardés sur ce téléphone.
export async function bilan() {
  const l = bareme(await locaux());
  const m = { envoyes: l.length, verifies: l.filter((r) => r.statut === 'verifie').length, aConfirmer: l.filter((r) => r.statut === 'a_confirmer').length };
  m.points = l.reduce((s, r) => s + r.points, 0);
  m.detail = l;
  m.badges = BADGES.map((b) => ({ ...b, obtenu: b.ok(m) }));
  m.plafondAtteint = l.some((r) => r.raison && r.raison.startsWith('Plafond'));
  return m;
}

// Interroge le serveur pour chaque signalement non définitif et renvoie les changements de statut (ancien, nouveau).
export async function verifierChangements() {
  const liste = (await kvGet('resultats')) || [], changements = [];
  let modifie = false;
  for (const r of liste.filter((x) => x.code_suivi && x.statut !== 'rejete').slice(0, 15)) {
    let s;
    try { s = await get('/api/suivi/' + encodeURIComponent(r.code_suivi)); } catch (e) { break; }      // hors ligne ou serveur absent : on réessaiera
    if (s && s.statut && s.statut !== r.statut) { changements.push({ code: r.code_suivi, ancien: r.statut, nouveau: s.statut }); r.statut = s.statut; r.message = s.message; modifie = true; }
  }
  if (modifie) {
    await kvSet('resultats', liste);
    const alertes = new Set((await kvGet('suivi_alertes')) || []);
    changements.forEach((c) => alertes.add(c.code));
    await kvSet('suivi_alertes', [...alertes]);
  }
  return changements;
}

export const alertesSuivi = async () => (await kvGet('suivi_alertes')) || [];
export const effacerAlertes = () => kvSet('suivi_alertes', []);
