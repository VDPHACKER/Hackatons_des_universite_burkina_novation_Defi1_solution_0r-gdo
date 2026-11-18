import { t } from './i18n.js';
// Écrans de l'application et menus par rôle. Une seule application : le menu et l'accueil s'adaptent à la personne connectée.
// Cette table sert seulement à l'affichage ; le serveur vérifie le rôle sur chaque route /api.
// `roles` : vide = écran public ; sinon rôles autorisés (l'administration passe partout).
// Acteurs du sujet : ménages (citoyens, sans compte), pré-collecteurs, brigade Laabal, mairie ; plus l'administration.
export const ECRANS = {
  accueil: { fichier: 'accueil', titre: 'Accueil', roles: [] },
  connexion: { fichier: 'connexion', titre: 'Connexion', roles: [] },
  carte: { fichier: 'carte', titre: 'Carte', roles: [] },
  signaler: { fichier: 'signaler', titre: 'Signaler', roles: [] },
  suivi: { fichier: 'suivi', titre: 'Suivi', roles: [] },
  points: { fichier: 'points', titre: 'Mes points et badges', roles: [] },
  droits: { fichier: 'droits', titre: 'Droits et devoirs des ménages', roles: [] },
  confidentialite: { fichier: 'confidentialite', titre: 'Confidentialité : vos données', roles: [] },
  commun: { fichier: 'commun', titre: 'Bien commun et export OSM', roles: [] },
  precollecteur: { fichier: 'precollecteur', titre: 'Ma tournée', roles: ['precollecteur'] },
  verifier: { fichier: 'verification', titre: 'À vérifier', roles: ['brigade'] },
  brigade: { fichier: 'brigade', titre: 'Interventions', roles: ['brigade'] },
  importer: { fichier: 'importer', titre: 'Importer une collecte', roles: ['brigade', 'mairie'] },
  mairie: { fichier: 'tableau', titre: 'Tableau de bord', roles: ['mairie'] },
  rapports: { fichier: 'mairie', titre: 'Rapports', roles: ['mairie'] },
  parametres: { fichier: 'parametres', titre: 'Paramètres', roles: [] },
  plan: { fichier: 'plan', titre: 'Plan de gestion', roles: ['mairie'] },
  scenarios: { fichier: 'scenarios', titre: 'Scénarios et simulation', roles: ['mairie'] },
  arrondissement: { fichier: 'arrondissement', titre: "Plan d'un arrondissement", roles: ['mairie'] },
  jury: { fichier: 'jury', titre: 'Épreuve en direct (jury)', roles: ['mairie'] },
  admin: { fichier: 'admin', titre: 'Administration', roles: ['admin'] },
};

// Onglets du bas (4 au plus) et feuille « Plus », par rôle. `visiteur` : personne n'est connecté (citoyen).
const COMMUNS = ['droits', 'confidentialite', 'commun', 'parametres'];     // Paramètres en dernier
export const MENU = {
  visiteur: { onglets: ['accueil', 'carte', 'signaler', 'suivi'], plus: ['points', ...COMMUNS, 'connexion'] },
  precollecteur: { onglets: ['accueil', 'precollecteur', 'carte', 'signaler'], plus: COMMUNS },
  brigade: { onglets: ['accueil', 'carte', 'verifier', 'brigade'], plus: ['importer', ...COMMUNS] },
  mairie: { onglets: ['mairie', 'carte', 'plan', 'scenarios'], plus: ['rapports', 'importer', ...COMMUNS] },
  admin: { onglets: ['admin', 'mairie', 'carte', 'verifier'], plus: ['plan', 'scenarios', 'brigade', 'rapports', 'importer', ...COMMUNS] },
};

export const menuDe = (role) => MENU[role] || MENU.visiteur;
// Titre d'un écran dans la langue choisie (le français sert de repli).
export const titre = (n) => t('nav.' + n, ECRANS[n].titre);
// Libellé court pour la barre du bas du téléphone : un seul mot, il doit tenir sous l'icône sur un écran de 320 px.
const COURT = { mairie: 'Tableau', plan: 'Plans', scenarios: 'Simulation', verifier: 'Vérifier', brigade: 'Terrain', precollecteur: 'Tournée',
  admin: 'Admin', points: 'Points', importer: 'Importer' };
export const titreCourt = (n) => t('tab.' + n, COURT[n] || ECRANS[n].titre);
// Libellés de la barre latérale (ordinateur), plus parlants que ceux de la barre du bas (téléphone).
const LATERAL = { mairie: 'Tableau de bord', signaler: 'Signalement', carte: 'Carte interactive', scenarios: 'Simulation & Scénarios', plan: 'Plans de gestion',
  arrondissement: "Plan d'un arrondissement", rapports: 'Rapports', parametres: 'Paramètres', jury: 'Épreuve en direct', droits: 'Droits et devoirs',
  confidentialite: 'Confidentialité', commun: 'Bien commun', suivi: 'Suivre un signalement', verifier: 'À vérifier', brigade: 'Interventions',
  points: 'Mes points et badges', importer: 'Importer une collecte' };
export const titreLateral = (n) => t('side.' + n, LATERAL[n] || ECRANS[n].titre);
