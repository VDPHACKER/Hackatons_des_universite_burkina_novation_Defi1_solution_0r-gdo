// La commune affichée par cette instance de l'application (Ouagadougou, Bobo-Dioulasso…) : décrite par GET /api/commune,
// jamais codée en dur dans l'interface. Sans réponse du serveur (hors ligne au premier lancement), on retombe sur Ouagadougou.
const DEFAUT = { code: 'ouaga', nom: 'Ouagadougou', marque: 'Orẽgdo', population: 2415266, menages: 502938, centre: [-1.53, 12.37], zoom: 10.5,
  pack: 'data/pack/', fond: 'data/pack/fond/', camions: 40, budget_pr_fcfa: 250000000 };
const CLE = 'oregdo.commune';
let info = null;

export const commune = () => info || DEFAUT;

export async function chargerCommune() {
  try {
    const r = await fetch('/api/commune');
    if (r.ok) { info = await r.json(); try { localStorage.setItem(CLE, JSON.stringify(info)); } catch (e) { /* stockage indisponible */ } return info; }
  } catch (e) { /* hors ligne : dernière commune connue */ }
  try { const m = localStorage.getItem(CLE); if (m) info = JSON.parse(m); } catch (e) { /* ignoré */ }
  return commune();
}
