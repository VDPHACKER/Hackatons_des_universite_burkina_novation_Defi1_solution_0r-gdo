// Installer l'application sur le téléphone (PWA) : bouton visible tant qu'elle n'est pas installée.
// Android (Chrome, Edge, Samsung) : le navigateur propose l'installation ; sinon et sur iPhone, on explique le geste à faire.
let invite = null;
const ecouteurs = new Set();
const prevenir = () => ecouteurs.forEach((f) => f());
export const installee = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
export const surChangement = (f) => { ecouteurs.add(f); return () => ecouteurs.delete(f); };
export const iphone = () => /iphone|ipad|ipod/i.test(navigator.userAgent);
window.addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); invite = e; prevenir(); });
window.addEventListener('appinstalled', () => { invite = null; prevenir(); });

// Renvoie un texte d'explication quand le navigateur ne propose pas lui-même l'installation.
export async function installer() {
  if (installee()) return 'L\'application est déjà installée sur ce téléphone.';
  if (invite) {
    invite.prompt();
    const { outcome } = await invite.userChoice.catch(() => ({ outcome: 'dismissed' }));
    invite = null; prevenir();
    return outcome === 'accepted' ? 'Installation en cours : l\'icône Orẽgdo apparaît sur l\'écran d\'accueil.' : '';
  }
  if (iphone()) return 'Sur iPhone : touchez le bouton Partager (carré avec une flèche) en bas de Safari, puis « Sur l\'écran d\'accueil ».';
  if (!window.isSecureContext) return 'L\'installation exige une adresse sécurisée (https). Ouvrez l\'application par son lien https.';
  return 'Ouvrez le menu du navigateur (les trois points ⋮ en haut à droite), puis « Installer l\'application » ou « Ajouter à l\'écran d\'accueil ».';
}
