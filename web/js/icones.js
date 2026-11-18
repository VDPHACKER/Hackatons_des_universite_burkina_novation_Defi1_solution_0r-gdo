// Icônes de navigation : dessins SVG « traits » (24 x 24), sans bibliothèque ni police d'icônes, donc disponibles hors ligne.
const D = {
  accueil: '<path d="M4 11 12 4l8 7v9h-5v-6H9v6H4z"/>',
  mairie: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  signaler: '<path d="M3 11v2a1 1 0 0 0 1 1h2l5 4V6L6 10H4a1 1 0 0 0-1 1z"/><path d="M15 9a4 4 0 0 1 0 6M18 6a8 8 0 0 1 0 12"/>',
  carte: '<path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2z"/><path d="M9 4v14M15 6v14"/>',
  scenarios: '<path d="M4 20V4M4 20h16"/><path d="M8 16l4-5 3 3 5-7"/>',
  plan: '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4h6v3H9zM9 12h6M9 16h6"/>',
  arrondissement: '<path d="M12 21s7-6 7-11a7 7 0 0 0-14 0c0 5 7 11 7 11z"/><circle cx="12" cy="10" r="2.5"/>',
  rapports: '<path d="M7 3h8l4 4v14H7z"/><path d="M15 3v4h4M10 12h6M10 16h6"/>',
  parametres: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>',
  suivi: '<circle cx="11" cy="11" r="6"/><path d="M16 16l5 5"/>',
  verifier: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5L16 9.5"/>',
  brigade: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
  jury: '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3"/>',
  admin: '<circle cx="9" cy="8" r="3"/><path d="M3 20c0-3.5 3-6 6-6s6 2.5 6 6"/><path d="M16 5a3 3 0 0 1 0 6M18 14c2 .8 3 2.8 3 6"/>',
  droits: '<path d="M12 4v16M6 20h12M5 7h14"/><path d="M5 7l-3 7a3 3 0 0 0 6 0zM19 7l-3 7a3 3 0 0 0 6 0z"/>',
  confidentialite: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  commun: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>',
  connexion: '<path d="M10 17l5-5-5-5M15 12H3"/><path d="M14 4h5a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-5"/>',
  camion: '<path d="M3 6h11v10H3zM14 9h4l3 3v4h-7"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>',
  corbeille: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/>',
  coche: '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l3 3 5-6"/>',
  camera: '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>',
  micro: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  locate: '<circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="8"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
  volume: '<path d="M4 10v4h4l5 4V6L8 10z"/><path d="M16 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11"/>',
  cloche: '<path d="M6 16v-5a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
  horsligne: '<path d="M7 18h10a4 4 0 0 0 .6-7.95A6 6 0 0 0 6.2 9.4 4.5 4.5 0 0 0 7 18z"/><path d="M4 4l16 16"/>',
  donnees: '<ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/>',
  licence: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 7.5-2"/>',
  ampoule: '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"/>',
  brouette: '<path d="M4 8h12l-2.2 7H7.2z"/><circle cx="9" cy="18.5" r="1.8"/><path d="M16 9l5-3"/>',
  tricycle: '<circle cx="5" cy="17" r="3"/><circle cx="18" cy="17" r="3"/><path d="M5 17h6l3-8h4M11 17l3-8M9 9h5"/>',
  filtres: '<path d="M4 6h16M7 12h10M10 18h4"/>',
  liste: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  croix: '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
  stop: '<rect x="7" y="7" width="10" height="10" rx="1.5"/>',
  sablier: '<path d="M7 3h10M7 21h10M8 3c0 5 4 5 4 9s-4 4-4 9M16 3c0 5-4 5-4 9s4 4 4 9"/>',
  play: '<path d="M8 5v14l11-7z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  alerte: '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18h.01"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  importer: '<path d="M12 15V4M7 9l5-5 5 5"/><path d="M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4"/>',
  points: '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
  langue: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z"/>',
  personne: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7"/>',
  sortie: '<path d="M10 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h5"/><path d="M15 8l4 4-4 4M19 12H9"/>',
};
D.precollecteur = D.camion; D.connexion = D.connexion || D.personne;

/** Fragment SVG d'une icône (couleur = couleur du texte). `taille` en pixels. */
export const icone = (nom, taille = 20) =>
  `<svg class="ico" width="${taille}" height="${taille}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${D[nom] || '<circle cx="12" cy="12" r="8"/>'}</svg>`;

/** Symbole de légende, identique à celui de la carte. */
const SYM = {
  depot: '<path d="M12 2.5 22 20.5H2z" fill="#d92d20" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/><path d="M12 9v5.5M12 17.2h.01" stroke="#fff" stroke-width="2" stroke-linecap="round"/>',
  verifie: '<circle cx="12" cy="12" r="10" fill="#12a150" stroke="#fff" stroke-width="1.6"/><path d="M7 12.4l3.2 3.2L17 8.8" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>',
  confirmer: '<circle cx="12" cy="12" r="10" fill="#f59e0b" stroke="#fff" stroke-width="1.6"/><text x="12" y="16.8" text-anchor="middle" font-size="13" font-weight="800" fill="#fff">?</text>',
  rejete: '<circle cx="12" cy="12" r="7.5" fill="#8b97a8" stroke="#fff" stroke-width="1.4"/><path d="M9.2 9.2l5.6 5.6M14.8 9.2l-5.6 5.6" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/>',
  pr: '<path d="M12 22.5C6 16 4.5 13 4.5 10a7.5 7.5 0 0 1 15 0c0 3-1.5 6-7.5 12.5z" fill="#1e7a46" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/><circle cx="12" cy="10" r="3" fill="#fff"/>',
  camion: '<circle cx="12" cy="12" r="10" fill="#2f6f9f" stroke="#fff" stroke-width="1.6"/><path d="M6.5 9h7v6h-7zM13.5 10.5h2.8l2 2.4V15h-4.8z" fill="#fff"/><circle cx="9" cy="16" r="1.6" fill="#2f6f9f" stroke="#fff"/><circle cx="15.5" cy="16" r="1.6" fill="#2f6f9f" stroke="#fff"/>',
  cet: '<rect x="3" y="3" width="18" height="18" rx="4" fill="#0b2a5b" stroke="#fff" stroke-width="1.6"/><path d="M7 15.5h10M8.5 11.5h7M10.5 7.5h3" stroke="#fff" stroke-width="2" stroke-linecap="round"/>',
};
export const symbole = (nom, taille = 18) => `<svg class="sym" width="${taille}" height="${taille}" viewBox="0 0 24 24" aria-hidden="true">${SYM[nom] || ''}</svg>`;
