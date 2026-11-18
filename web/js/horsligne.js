// Utilisation sans réseau : savoir si le téléphone est prêt, et tout préparer d'un geste.
// Le service worker garde l'application et la carte ; les modèles de masquage (≈ 45 Mo) et les dernières données
// ne sont gardés qu'après un premier téléchargement : c'est ce que fait preparerHorsLigne().
import { preparer } from './masquage.js';
import { get } from './api.js';
import { kvGet } from './db.js';

const DONNEES = ['/api/public/depotoirs', '/api/plan', '/api/public/defi', '/api/scenario'];

async function nbEntrees(prefixe) {
  if (!('caches' in window)) return 0;
  let n = 0;
  for (const k of await caches.keys()) if (k.startsWith(prefixe)) n += (await (await caches.open(k)).keys()).length;
  return n;
}

// { application, masquage, donnees } : chacun vrai quand il est disponible sans réseau.
export async function etatHorsLigne() {
  const [app, masq, dep] = await Promise.all([nbEntrees('oregdo-v'), nbEntrees('oregdo-masquage'), kvGet('api:/api/public/depotoirs')]);
  return { application: app >= 40, masquage: masq >= 5, donnees: dep !== undefined };
}

export async function preparerHorsLigne(avance = () => {}) {
  if (!navigator.onLine) throw new Error('Il faut du réseau pour préparer l\'utilisation sans réseau.');
  avance('Application et carte…');
  if (navigator.serviceWorker) await navigator.serviceWorker.ready;
  avance('Masquage des visages et plaques (environ 45 Mo, une seule fois)…');
  await preparer();
  avance('Dernières données de la commune…');
  await Promise.allSettled(DONNEES.map((p) => get(p)));
  return etatHorsLigne();
}

// Au démarrage : si le téléphone est en Wi-Fi (ou sur un réseau rapide sans économie de données), on prépare en silence.
export function preparationAutomatique() {
  const c = navigator.connection;
  const wifi = !c || c.type === 'wifi' || c.type === 'ethernet' || (!c.saveData && c.effectiveType === '4g');
  if (!navigator.onLine || !wifi || document.body.classList.contains('eco')) return;
  setTimeout(() => { etatHorsLigne().then((e) => { if (!e.masquage || !e.donnees) preparerHorsLigne().catch(() => {}); }); }, 8000);
}
