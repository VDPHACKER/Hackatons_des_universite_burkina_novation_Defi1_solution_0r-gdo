// IndexedDB : file d'attente hors ligne (signalements) + petit stockage clé/valeur (dernières données).
let _db;
const ouvrirBase = (nom, creer) => new Promise((res, rej) => {
  const r = indexedDB.open(nom, 1);
  r.onupgradeneeded = () => {
    if (!creer) { r.transaction.abort(); return; }          // ancienne base absente : on ne la crée pas pour rien
    const d = r.result; d.createObjectStore('kv'); d.createObjectStore('queue', { keyPath: 'qid', autoIncrement: true });
  };
  r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
});
const lireTout = (d, st, cles) => new Promise((res) => {
  try { const q = cles ? d.transaction(st).objectStore(st).getAllKeys() : d.transaction(st).objectStore(st).getAll(); q.onsuccess = () => res(q.result || []); q.onerror = () => res([]); }
  catch (e) { res([]); }
});

// Reprise de l'ancienne base du téléphone (ancien nom technique « laabal ») : les signalements en attente d'envoi et les codes
// de suivi ne doivent jamais être perdus lors d'une mise à jour de l'application. Faite une seule fois, puis l'ancienne base est effacée.
async function reprendreAncienne(d) {
  try {
    if (localStorage.getItem('oregdo.reprise') === '1') return;
    const anciennes = indexedDB.databases ? (await indexedDB.databases()).map((x) => x.name) : ['laabal'];
    if (!anciennes.includes('laabal')) { localStorage.setItem('oregdo.reprise', '1'); return; }
    const a = await ouvrirBase('laabal', false);
    const file = await lireTout(a, 'queue'), cles = await lireTout(a, 'kv', true), valeurs = await lireTout(a, 'kv');
    a.close();
    await new Promise((res, rej) => {
      const t = d.transaction(['queue', 'kv'], 'readwrite');
      file.forEach((it) => { const { qid, ...reste } = it; t.objectStore('queue').add(reste); });
      cles.forEach((k, i) => { if (!String(k).startsWith('api:')) t.objectStore('kv').put(valeurs[i], k); });
      t.oncomplete = res; t.onerror = () => rej(t.error);
    });
    indexedDB.deleteDatabase('laabal');
    localStorage.setItem('oregdo.reprise', '1');
  } catch (e) { /* reprise impossible (navigateur ancien) : la nouvelle base fonctionne quand même */ }
}

function open() {
  if (_db) return _db;
  _db = ouvrirBase('oregdo', true).then(async (d) => { await reprendreAncienne(d); return d; });
  return _db;
}
const tx = async (st, mode, fn) => { const d = await open(); return new Promise((res, rej) => { const t = d.transaction(st, mode); const q = fn(t.objectStore(st)); t.oncomplete = () => res(q && q.result); t.onerror = () => rej(t.error); }); };
export const kvGet = (k) => tx('kv', 'readonly', (s) => s.get(k)).catch(() => undefined);
export const kvSet = (k, v) => tx('kv', 'readwrite', (s) => s.put(v, k)).catch(() => {});
// À la fermeture de session : oublier les lectures privées (copies d'API) et le journal local, pour un téléphone partagé.
export const kvEffacerPrive = () => tx('kv', 'readwrite', (s) => {
  const r = s.getAllKeys();
  r.onsuccess = () => r.result.filter((k) => String(k).startsWith('api:') || k === 'journal').forEach((k) => s.delete(k));
  return r;
}).catch(() => {});
export const qAdd = (item) => tx('queue', 'readwrite', (s) => s.add(item));
export const qAll = () => tx('queue', 'readonly', (s) => s.getAll()).then((a) => a || []).catch(() => []);
export const qDel = (id) => tx('queue', 'readwrite', (s) => s.delete(id));
export const qCount = () => tx('queue', 'readonly', (s) => s.count()).then((n) => n || 0).catch(() => 0);
export const qPut = (item) => tx('queue', 'readwrite', (s) => s.put(item));
