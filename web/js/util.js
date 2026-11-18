import { t } from './i18n.js';
export const $ = (s, r = document) => r.querySelector(s);
export const $$ = (s, r = document) => [...r.querySelectorAll(s)];
export const esc = (t) => String(t ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const nf = (n, d = 0) => (n == null || isNaN(n) ? '-' : Number(n).toLocaleString('fr-FR', { maximumFractionDigits: d, minimumFractionDigits: 0 }));
export const STATUTS = {
  verifie: ['Vérifié', 'verifie', '#0a8a3a'],
  a_confirmer: ['À confirmer', 'a_confirmer', '#e08a00'],
  rejete: ['Rejeté', 'rejete', '#c4202a'],
};
export const badge = (s) => { const [l, c] = STATUTS[s] || [s, 'info']; return `<span class="badge b-${c}">${esc(t('st.' + s, l))}</span>`; };
let tt;
export function toast(msg, ms = 4000) {
  const t = $('#toast'); t.textContent = msg; t.classList.add('on');
  clearTimeout(tt); tt = setTimeout(() => t.classList.remove('on'), ms);
}
export function motifsHtml(motifs) {
  if (!motifs || !motifs.length) return '<p class="mut">Aucun motif détaillé.</p>';
  return '<ul class="motifs">' + motifs.map((m) => {
    if (typeof m === 'string') return `<li class="na">${esc(propre(m))}</li>`;
    const o = okMotif(m); const c = o === true ? 'ok' : o === false ? 'ko' : 'na';
    const pts = m.points != null ? ` <span class="mut petit">(${m.points}${m.max != null ? '/' + m.max : ''} pts)</span>` : '';
    return `<li class="${c}">${esc(propre(m.message || m.motif || m.texte || m.controle))}${pts}</li>`;
  }).join('') + '</ul>';
}
export function normList(r) {
  if (!r) return [];
  if (Array.isArray(r)) return r;
  const a = r.signalements || r.items || r.resultats || r.depotoirs;
  if (Array.isArray(a)) return a;
  if (r.type === 'FeatureCollection') return r.features.map((f) => ({ ...f.properties, lon: f.geometry?.coordinates?.[0], lat: f.geometry?.coordinates?.[1], id: f.properties?.id ?? f.id }));
  return [];
}
export const pick = (o, keys, d) => { for (const k of keys) if (o && o[k] != null) return o[k]; return d; };
export function fc(r) { return r && r.type === 'FeatureCollection' ? r : { type: 'FeatureCollection', features: [] }; }
export function ago(ts) {
  if (!ts) return 'jamais';
  const s = (Date.now() - ts) / 1000;
  if (s < 90) return "à l'instant";
  if (s < 3600) return `il y a ${Math.round(s / 60)} min`;
  if (s < 86400) return `il y a ${Math.round(s / 3600)} h`;
  return `il y a ${Math.round(s / 86400)} j`;
}
export const wait = (ms) => new Promise((r) => setTimeout(r, ms));
export function download(name, text, type = 'application/json') {
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name;
  document.body.append(a); a.click(); a.remove();
}
export function waLink(txt) { return 'https://wa.me/?text=' + encodeURIComponent(txt); }

// ---- Ajouts (correction après évaluation) ----
export function dateFr(x) {
  const d = x ? new Date(x) : null;
  return d && !isNaN(d) ? d.toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }) : 'date inconnue';
}
export function okMotif(m) { return m.ok === true || m.etat === 'ok' ? true : m.ok === false || m.etat === 'echec' ? false : null; }
// Message lisible pour une erreur d'API (jamais « Rejeté » pour une panne technique).
export function erreurTexte(e) {
  if (e && e.status === 401) return 'Connexion requise ou session expirée : connectez-vous. ' + (e.message && !/^Erreur/.test(e.message) ? '(' + e.message + ')' : '');
  if (e && e.status === 403) return "Votre rôle n'autorise pas cette action. " + (e.message && !/^Erreur/.test(e.message) ? '(' + e.message + ')' : '');
  if (e && e.status === 0) return 'Pas de connexion. Réessayez plus tard.';
  return (e && e.message) || 'Erreur inconnue.';
}
// Lecture à voix haute (voix française du navigateur ; mooré et dioula non disponibles).
export function ecouter(texte) {
  if (!('speechSynthesis' in window)) { toast("La lecture à voix haute n'est pas disponible sur ce navigateur."); return; }
  const s = window.speechSynthesis;
  if (s.speaking) { s.cancel(); return; }
  const u = new SpeechSynthesisUtterance(texte); u.lang = 'fr-FR'; u.rate = 0.9;
  const v = s.getVoices().find((x) => x.lang && x.lang.toLowerCase().startsWith('fr'));
  if (v) u.voice = v; else toast('Aucune voix française trouvée sur cet appareil : la lecture peut être en anglais.');
  s.speak(u);
}

// Identifiant d'appareil anonyme (aléatoire, gardé sur le téléphone) : limitation de débit et corroboration, jamais un nom.
export function appareil() {
  try { let a = localStorage.getItem('oregdo.appareil'); if (!a) { a = 'a' + crypto.randomUUID(); localStorage.setItem('oregdo.appareil', a); } return a; } catch (e) { return 'inconnu'; }
}

export const propre =(t) => String(t || "").replace(/\s*\(couche des b[âa]timents non disponible dans le pack\)/i, "");

// Position GPS : haute précision d'abord, puis précision normale si elle échoue ; messages qui disent la vraie cause.
export const raisonGps = (e) => !window.isSecureContext
  ? "Le navigateur bloque le GPS sur une adresse non sécurisée (http). Ouvrez l'application en https, ou saisissez la position à la main."
  : e && e.code === 1 ? 'Localisation refusée : autorisez-la pour ce site dans les réglages du navigateur, ou saisissez la position à la main.'
  : e && e.code === 3 ? "Délai dépassé : sortez à l'air libre et réessayez, ou saisissez la position à la main."
  : 'Position introuvable : réessayez, ou saisissez-la à la main.';
// Position GPS fiable. Le premier relevé d'un téléphone vient souvent du réseau (précision de 500 m à plusieurs km) ou d'un
// ancien cache : on ÉCOUTE donc le GPS et on garde le meilleur relevé, jusqu'à la précision voulue ou la fin du délai.
// `progression(p)` reçoit chaque relevé meilleur que le précédent (affichage « on affine… »). Renvoie une fonction d'arrêt
// qui termine tout de suite avec le meilleur relevé obtenu (bouton « Utiliser cette position »).
export function localiser(succes, echec, { precisionVoulue = 25, dureeMax = 30000, progression } = {}) {
  if (!navigator.geolocation) { echec({ code: 0, message: 'absent' }); return () => {}; }
  if (!window.isSecureContext) { echec({ code: 1, message: 'http' }); return () => {}; }
  let meilleur = null, fini = false, id = null;
  const terminer = (resultat) => {
    if (fini) return; fini = true;
    if (id != null) navigator.geolocation.clearWatch(id);
    clearTimeout(minuterie);
    if (resultat) succes(resultat);
  };
  const recu = (p) => {
    if (fini || !p || !p.coords) return;
    if (!meilleur || p.coords.accuracy < meilleur.coords.accuracy) { meilleur = p; if (progression) progression(p); }
    if (p.coords.accuracy <= precisionVoulue) terminer(p);
  };
  const erreur = (e) => { if (!fini && e && e.code === 1) { terminer(null); echec(e); } };   // refus : inutile d'attendre ; sinon on patiente
  const minuterie = setTimeout(() => {
    if (fini) return;
    if (meilleur) { terminer(meilleur); return; }
    if (id != null) navigator.geolocation.clearWatch(id);
    fini = true;                                                              // aucun relevé GPS : dernier recours, la position du réseau
    navigator.geolocation.getCurrentPosition(succes, echec, { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 });
  }, dureeMax);
  id = navigator.geolocation.watchPosition(recu, erreur, { enableHighAccuracy: true, maximumAge: 0, timeout: dureeMax });
  return () => terminer(meilleur);
}
