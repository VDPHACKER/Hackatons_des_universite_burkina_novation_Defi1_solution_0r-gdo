// Langues de l'application : français (langue source), dioula (dyu) et mooré (mos).
// t(cle, texte_francais) renvoie la traduction si elle existe, SINON le français : une phrase non traduite n'est jamais vide ni fausse.
// Les dictionnaires sont dans web/data/i18n/<code>.json ({ "_statut": "brouillon", "cle": "texte" }) et se remplissent depuis une feuille CSV :
// voir scripts/traductions_csv.py et docs/14-langues-locales.md. Les traductions doivent être validées par des locuteurs natifs.
export const LANGUES = { fr: 'Français', dyu: 'Dioula', mos: 'Mooré' };
const CLE = 'oregdo.langue';
let courante = 'fr', dico = {};

export const langue = () => courante;
export const statut = () => (courante === 'fr' ? 'source' : dico._statut || 'brouillon');

export function t(cle, fr, vars) {
  let s = (courante !== 'fr' && typeof dico[cle] === 'string' && dico[cle]) || fr;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(v);
  return s;
}

// À appeler avant d'afficher quoi que ce soit : lit le choix mémorisé et charge le dictionnaire (en cache hors ligne).
export async function initLangue() {
  let c = 'fr'; try { c = localStorage.getItem(CLE) || 'fr'; } catch (e) { /* stockage indisponible : français */ }
  if (!LANGUES[c]) c = 'fr';
  courante = c;
  if (c !== 'fr') {
    try { const r = await fetch(`data/i18n/${c}.json`); if (r.ok) dico = await r.json(); else courante = 'fr'; }
    catch (e) { courante = 'fr'; }
  }
  document.documentElement.lang = courante;
}

export function choisir(code) {
  if (!LANGUES[code]) return;
  try { localStorage.setItem(CLE, code); } catch (e) { /* non mémorisé : tant pis */ }
  location.reload();
}
