import { commune } from './commune.js';
// Module unique qui parle au contrat d'API (docs/12). Authentification : jeton signé dans `Authorization: Bearer`.
// Aucune donnée inventée : si le serveur ne répond pas, on le dit (ou on montre le dernier cache de lecture, marqué périmé).
import { kvGet, kvSet } from './db.js';
import { jeton, fermer } from './session.js';

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export const etat = { synthetique: null, demo: false, online: navigator.onLine, derniere: Number(safe('oregdo.fraicheur')) || 0, perime: false };
const ecouteurs = new Set();
export const surEtat = (f) => ecouteurs.add(f);
const notifier = () => ecouteurs.forEach((f) => f(etat));
function safe(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function marquerOk() { etat.derniere = Date.now(); etat.online = true; etat.online = navigator.onLine; etat.perime = false; try { localStorage.setItem('oregdo.fraicheur', String(etat.derniere)); } catch (e) {} notifier(); }
window.addEventListener('online', () => { etat.online = true; notifier(); });
window.addEventListener('offline', () => { etat.online = false; notifier(); });
// Serveur injoignable alors que le téléphone a du réseau (tunnel, Wi-Fi capricieux) : on reteste toutes les 10 s,
// et l'état repasse « en ligne » dès que le serveur répond, sans attendre une action de la personne.
let sonde = null;
function horsLigne() {
  etat.online = false; notifier();
  if (sonde) return;
  sonde = setInterval(async () => {
    if (!navigator.onLine) return;
    try { const r = await fetchT('GET', '/api/sante', null, 8000); if (r.ok) { clearInterval(sonde); sonde = null; marquerOk(); window.dispatchEvent(new Event('online')); } }
    catch (e) { /* toujours injoignable */ }
  }, 10000);
}

function noterSynth(j) {
  const o = j && (j.stats || j);
  if (o && typeof o === 'object' && 'synthetique' in o && !Array.isArray(o)) { etat.synthetique = !!o.synthetique; notifier(); }
  else if (j && j.features && j.features[0] && j.features[0].properties && 'synthetique' in j.features[0].properties) { etat.synthetique = !!j.features[0].properties.synthetique; notifier(); }
}
async function fetchT(method, path, body, ms = 20000) {
  const c = new AbortController(); const t = setTimeout(() => c.abort(), ms);
  try {
    return await fetch(path, { method, signal: c.signal, headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...(jeton() ? { Authorization: 'Bearer ' + jeton() } : {}) }, body: body ? JSON.stringify(body) : undefined });
  } finally { clearTimeout(t); }
}

export async function appel(method, path, body, ms) {
  let r;
  try { r = await fetchT(method, path, body, ms); }
  catch (e) {
    // Réponse lente (délai dépassé) : le réseau marche, le serveur calcule. Ce n'est PAS une coupure : on ne passe pas « hors ligne ».
    const lent = e && e.name === 'AbortError';
    if (lent && method !== 'GET') throw new ApiError(0, 'Le serveur n\'a pas répondu à temps. Réessayez dans un instant.');
    if (!lent) horsLigne();
    if (method === 'GET') {
      const c = await kvGet('api:' + path);
      if (c !== undefined) { etat.perime = true; notifier(); return c; }
    }
    throw new ApiError(0, lent ? 'Le serveur met du temps à répondre. Réessayez dans un instant.' : 'Pas de connexion. Réessayez plus tard.');
  }
  if (r.ok) {
    const j = await r.json().catch(() => ({}));
    marquerOk(); noterSynth(j);
    if (method === 'GET') kvSet('api:' + path, j);
    return j;
  }
  const txt = await r.text().catch(() => '');
  let d = {}; try { d = JSON.parse(txt); } catch (e) {}
  // Session refusée par le serveur (expirée, révoquée, compte désactivé) : on ferme la session ici, l'application renvoie à la connexion.
  if (r.status === 401 && jeton()) fermer();
  throw new ApiError(r.status, typeof d.detail === 'string' ? d.detail : Array.isArray(d.detail) ? 'Champ invalide : ' + d.detail.map((x) => (x.loc || []).slice(1).join('.')).join(', ') : d.message || `Erreur ${r.status}`);
}
// Envoi d'un fichier (import CSV ou GeoJSON de l'enquêteur) : multipart, même gestion d'erreurs que `appel`.
export async function televerser(path, fichier, champ = 'fichier') {
  const corps = new FormData(); corps.append(champ, fichier);
  let r;
  try { r = await fetch(path, { method: 'POST', body: corps, headers: jeton() ? { Authorization: 'Bearer ' + jeton() } : {} }); }
  catch (e) { throw new ApiError(0, 'Pas de connexion. Réessayez plus tard.'); }
  const d = await r.json().catch(() => ({}));
  if (r.ok) { marquerOk(); return d; }
  if (r.status === 401 && jeton()) fermer();
  throw new ApiError(r.status, typeof d.detail === 'string' ? d.detail : `Erreur ${r.status}`);
}
export const get = (p) => appel('GET', p);
export const post = (p, b, ms) => appel('POST', p, b ?? {}, ms);
export const put = (p, b, ms) => appel('PUT', p, b, ms);

// Scénario : on réutilise les noms de clés renvoyés par le serveur (alias tolérés).
export const ALIAS = {
  population: ['population', 'facteur_population'],   // le moteur réel stocke un FACTEUR (1,0 = RGPH 2019)
  taux_abonnement: ['taux_abonnement', 'abonnement', 'taux_abonnement_pct'],
  camions: ['camions', 'camions_nombre', 'nombre_camions'],
  frequence: ['frequence_jours', 'frequence_collecte_jours', 'frequence'],
  budget: ['budget_fcfa', 'budget_pr_fcfa', 'budget'],
  saison_pluies: ['saison_pluies', 'pluies'],
  agents_individuels: ['agents_individuels'],         // simulation : tricycles individuels (pannes)
  mairie_decisionnelle: ['mairie_decisionnelle'],     // simulation : la mairie décide d'acheter des camions
  taux_tri: ['taux_tri'],                              // valorisation : part des ménages qui trient et revendent leurs recyclables
};
export function lireScenario(o) {
  const s = {};
  for (const [k, al] of Object.entries(ALIAS)) { const a = al.find((x) => o && o[x] != null); s[k] = a ? o[a] : undefined; s['_cle_' + k] = a || al[0]; }
  const sc = o && (o.scenario || o);
  if (sc !== o) return lireScenario(sc);
  if (s.taux_abonnement > 1) s.taux_abonnement /= 100;
  if (s._cle_population === 'facteur_population' && s.population != null) s.population *= commune().population;
  return s;
}
// Population de référence (RGPH 2019) : le moteur exprime la population en facteur de cette valeur.
export const POP_REF = 2415266;
export function ecrireScenario(s) {
  const o = {};
  for (const k of Object.keys(ALIAS)) {
    if (s[k] == null) continue;
    let v = s[k];
    if (k === 'taux_abonnement' && s['_cle_' + k] === 'taux_abonnement_pct') v = Math.round(v * 100);
    if (k === 'population' && s['_cle_' + k] === 'facteur_population') v = v / commune().population;
    o[s['_cle_' + k] || ALIAS[k][0]] = v;
  }
  return o;
}
export function lireKpi(k = {}) {
  const cv = pick(k, ['taux_couverture_production', 'couverture', 'couverture_pct', 'couverture_population']);
  let fu = pick(k, ['fuite', 'fuite_pct', 'taux_fuite']);
  const fuT = pick(k, ['fuite_tonnes', 'fuite_t', 'tonnes_fuite_j']);
  const prod = pick(k, ['tonnes_produites_j']);
  if (fu == null && fuT != null && prod) fu = fuT / prod;   // part des déchets qui n'est pas évacuée
  return {
    distance_km: pick(k, ['distance_km', 'distance_totale_km', 'distance']),
    cout_fcfa: pick(k, ['cout_fcfa', 'cout_total_fcfa', 'cout_collecte_fcfa', 'cout']),
    couverture: cv == null ? undefined : cv <= 1 ? cv * 100 : cv,
    tonnes: pick(k, ['tonnes_evacuees', 'tonnes_evacuees_j', 'tonnes', 'tonnes_jour']),
    fuite: fu == null ? undefined : fu <= 1 ? fu * 100 : fu,
    fuite_t: fuT,
    valorise: k.tonnes_valorisees_j,
    recette_valo: k.recettes_valorisation_j_fcfa ? k.recettes_valorisation_j_fcfa.total : undefined,
  };
}
function pick(o, keys) { for (const k of keys) if (o && o[k] != null) return o[k]; }
export function lirePlan(p = {}) {
  return {
    pr: p.pr || p.points_regroupement || p.points || { type: 'FeatureCollection', features: [] },
    tournees: p.tournees || { type: 'FeatureCollection', features: [] },
    kpi: lireKpi(p.kpi || p.kpis || {}),
    brut: p,
    temps_s: p.temps_calcul_s ?? (p.temps_calcul_ms != null ? p.temps_calcul_ms / 1000 : p.duree_s),
  };
}

// Séries de simulation : le moteur renvoie des LIGNES (serie[{jour, ...}]), l'interface trace des COLONNES.
const COLONNES_SERIE = {
  depotoirs_tonnes: 'stock_depotoirs_tonnes', couverture: 'taux_couverture',
  cout_cumule_fcfa: 'budget_consomme_fcfa', fuite_tonnes: 'tonnes_fuite_depotoirs',
};
export function lireSeries(x = {}) {
  if (x.series && !Array.isArray(x.series)) return x.series;      // déjà en colonnes (mode démo)
  const lignes = x.serie || (x.reference && x.reference.serie) || [];
  const s = { jour: lignes.map((l) => l.jour) };
  for (const [k, src] of Object.entries(COLONNES_SERIE)) s[k] = lignes.map((l) => l[src] ?? 0);
  return s;
}

// Remise à zéro : renvoie le scénario de référence au serveur (utile après des essais ou avant une démonstration).
export async function reinitialiserScenario() {
  const s = await get('/api/scenario');
  const ref = s.reference || (s.scenario && s.scenario.reference);
  if (!ref) throw new ApiError(0, "Le serveur ne fournit pas de situation de référence.");
  const corps = { ...ref };
  await put('/api/scenario', corps);
  return post('/api/plan/recalculer');
}
