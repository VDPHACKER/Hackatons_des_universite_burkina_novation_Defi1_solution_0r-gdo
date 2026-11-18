// Sous-navigation à onglets à l'intérieur d'un écran : évite de multiplier les entrées du menu principal.
import { esc } from './util.js';
import { ECRANS } from './acces.js';
import { autorise } from './session.js';
export const PLANS = [['plan', 'Commune'], ['arrondissement', 'Par arrondissement']];
export const SIMULATION = [['scenarios', 'Scénarios'], ['jury', 'Épreuve en direct']];
export const sousNav = (items, actif) => `<nav class="sous-nav" aria-label="Sections">${items.filter(([id]) => autorise(ECRANS[id]?.roles)).map(([id, nom]) => `<a href="#/${id}"${id === actif ? ' aria-current="page"' : ''}>${esc(nom)}</a>`).join('')}</nav>`;
