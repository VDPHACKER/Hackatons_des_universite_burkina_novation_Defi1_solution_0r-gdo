// Sous-navigation à onglets à l'intérieur d'un écran : évite de multiplier les entrées du menu principal.
import { esc } from './util.js';
export const PLANS = [['plan', 'Commune'], ['arrondissement', 'Par arrondissement']];
export const SIMULATION = [['scenarios', 'Scénarios'], ['jury', 'Épreuve en direct']];
export const sousNav = (items, actif) => `<nav class="sous-nav" aria-label="Sections">${items.map(([id, nom]) => `<a href="#/${id}"${id === actif ? ' aria-current="page"' : ''}>${esc(nom)}</a>`).join('')}</nav>`;
