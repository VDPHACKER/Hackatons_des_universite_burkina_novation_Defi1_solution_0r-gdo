// Masquage automatique des visages et des plaques d'immatriculation, SUR LE TÉLÉPHONE et hors ligne.
// La photo originale ne quitte jamais l'appareil : seule la version masquée est envoyée.
//   visages : MediaPipe BlazeFace (Apache-2.0)        plaques : YOLOv9-t (MIT) via onnxruntime-web (MIT)
// Voir web/vendor/masquage/LICENCES.md. Règle de sûreté : si le masquage ne peut pas s'exécuter, la photo n'est PAS envoyée.
const BASE = '/vendor/masquage/';
const TAILLE_PLAQUES = 384;
const SEUIL_VISAGE = 0.3, SEUIL_PLAQUE = 0.25;        // seuils bas : on préfère masquer trop que pas assez
const SEUIL_PERSONNE = 0.3;
const MARGE_VISAGE = 0.25, MARGE_PLAQUE = 0.15;
const PART_TETE = 0.28;                                // part haute de la silhouette masquée quand aucun visage n'y est reconnu
// Passes : image entière + 4 tuiles qui se chevauchent (les visages et plaques lointains sont petits).
const TUILES = [[0, 0, 1, 1], [0, 0, .6, .6], [.4, 0, .6, .6], [0, .4, .6, .6], [.4, .4, .6, .6]];

let moteurs = null;                                    // promesse partagée : chargé une seule fois
export const etat = { pret: false, erreur: null };

async function chargerMoteurs(avance) {
  const dire = (t) => avance && avance(t);
  dire('Chargement du masquage des visages…');
  const mp = await import(BASE + 'mediapipe/vision_bundle.mjs');
  const fichiers = await mp.FilesetResolver.forVisionTasks(BASE + 'mediapipe/wasm');
  const visages = await mp.FaceDetector.createFromOptions(fichiers, {
    baseOptions: { modelAssetPath: BASE + 'modeles/blaze_face_short_range.tflite', delegate: 'CPU' },
    runningMode: 'IMAGE', minDetectionConfidence: SEUIL_VISAGE,
  });
  // Personnes entières : filet de sécurité pour les gens trop loin ou de profil, dont le visage n'est pas reconnu.
  const personnes = await mp.ObjectDetector.createFromOptions(fichiers, {
    baseOptions: { modelAssetPath: BASE + 'modeles/efficientdet_lite0.tflite', delegate: 'CPU' },
    runningMode: 'IMAGE', scoreThreshold: SEUIL_PERSONNE, categoryAllowlist: ['person'], maxResults: 20,
  });
  dire('Chargement du masquage des plaques…');
  const ort = await import(BASE + 'ort/ort.wasm.min.mjs');
  ort.env.wasm.wasmPaths = BASE + 'ort/'; ort.env.wasm.numThreads = 1; ort.env.wasm.proxy = false;
  const plaques = await ort.InferenceSession.create(BASE + 'modeles/yolo-v9-t-384-license-plates-end2end.onnx', { executionProviders: ['wasm'] });
  return { visages, personnes, plaques, ort };
}
export function preparer(avance) {                     // à appeler tôt (réseau disponible) pour que tout soit en cache hors ligne
  if (!moteurs) moteurs = chargerMoteurs(avance).then((m) => { etat.pret = true; return m; }).catch((e) => { etat.erreur = e; moteurs = null; throw e; });
  return moteurs;
}

const toile = (w, h) => { const c = document.createElement('canvas'); c.width = Math.max(1, Math.round(w)); c.height = Math.max(1, Math.round(h)); return c; };

// Image carrée 384×384 avec bandes grises (letterbox), valeurs 0..1, ordre RGB puis CHW.
function versTenseur(source, sx, sy, sw, sh) {
  const c = toile(TAILLE_PLAQUES, TAILLE_PLAQUES), g = c.getContext('2d', { willReadFrequently: true });
  g.fillStyle = 'rgb(114,114,114)'; g.fillRect(0, 0, c.width, c.height);
  const k = TAILLE_PLAQUES / Math.max(sw, sh), w = sw * k, h = sh * k, ox = (TAILLE_PLAQUES - w) / 2, oy = (TAILLE_PLAQUES - h) / 2;
  g.drawImage(source, sx, sy, sw, sh, ox, oy, w, h);
  const px = g.getImageData(0, 0, c.width, c.height).data, n = TAILLE_PLAQUES * TAILLE_PLAQUES, f = new Float32Array(3 * n);
  for (let i = 0; i < n; i++) { f[i] = px[4 * i] / 255; f[n + i] = px[4 * i + 1] / 255; f[2 * n + i] = px[4 * i + 2] / 255; }
  return { f, k, ox, oy };
}

async function plaquesDans(m, bmp, [tx, ty, tw, th]) {
  const sx = tx * bmp.width, sy = ty * bmp.height, sw = tw * bmp.width, sh = th * bmp.height;
  const { f, k, ox, oy } = versTenseur(bmp, sx, sy, sw, sh);
  const sortie = await m.plaques.run({ images: new m.ort.Tensor('float32', f, [1, 3, TAILLE_PLAQUES, TAILLE_PLAQUES]) });
  const d = sortie.output0.data, lignes = sortie.output0.dims[0], res = [];
  for (let i = 0; i < lignes; i++) {
    const [, x1, y1, x2, y2, , score] = Array.from(d.slice(i * 7, i * 7 + 7));
    if (score >= SEUIL_PLAQUE) res.push({ x: sx + (x1 - ox) / k, y: sy + (y1 - oy) / k, w: (x2 - x1) / k, h: (y2 - y1) / k, score });
  }
  return res;
}

function visagesDans(m, bmp, [tx, ty, tw, th]) {
  const sx = tx * bmp.width, sy = ty * bmp.height, sw = tw * bmp.width, sh = th * bmp.height;
  const c = toile(Math.min(sw, 1024), Math.min(sw, 1024) * sh / sw); c.getContext('2d').drawImage(bmp, sx, sy, sw, sh, 0, 0, c.width, c.height);
  const k = sw / c.width;
  return m.visages.detect(c).detections.map((d) => ({ x: sx + d.boundingBox.originX * k, y: sy + d.boundingBox.originY * k, w: d.boundingBox.width * k, h: d.boundingBox.height * k, score: d.categories?.[0]?.score ?? 0 }));
}

function personnesDans(m, bmp, [tx, ty, tw, th]) {
  const sx = tx * bmp.width, sy = ty * bmp.height, sw = tw * bmp.width, sh = th * bmp.height;
  const c = toile(Math.min(sw, 1024), Math.min(sw, 1024) * sh / sw); c.getContext('2d').drawImage(bmp, sx, sy, sw, sh, 0, 0, c.width, c.height);
  const k = sw / c.width;
  return m.personnes.detect(c).detections.map((d) => ({ x: sx + d.boundingBox.originX * k, y: sy + d.boundingBox.originY * k, w: d.boundingBox.width * k, h: d.boundingBox.height * k, score: d.categories?.[0]?.score ?? 0 }));
}
const contient = (a, b) => { const cx = b.x + b.w / 2, cy = b.y + b.h / 2; return cx >= a.x && cx <= a.x + a.w && cy >= a.y && cy <= a.y + a.h; };

// Fusionne les boîtes qui se recouvrent largement (même objet vu dans deux passes).
function fusionner(boites) {
  const r = [];
  for (const b of boites.sort((a, c) => c.score - a.score)) {
    const doublon = r.some((a) => { const ix = Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)), iy = Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y)); return ix * iy > 0.5 * Math.min(a.w * a.h, b.w * b.h); });
    if (!doublon) r.push(b);
  }
  return r;
}

/** Détecte puis masque (aplat sombre, non réversible). Renvoie { blob, visages, plaques, boites, statut }.
 *  statut : 'masque' (le contrôle a tourné, avec ou sans résultat) ou 'indisponible' (la photo ne doit PAS être envoyée). */
export async function masquer(fichier, { avance, qualite = 0.7, maxPx = 1024, tuiles = true } = {}) {
  let m;
  try { m = await preparer(avance); } catch (e) { return { statut: 'indisponible', erreur: String(e && e.message || e) }; }
  try {
    const bmp = await createImageBitmap(fichier, { imageOrientation: 'from-image' });
    const passes = tuiles ? TUILES : TUILES.slice(0, 1);
    let vis = [], pla = [], per = [];
    for (let i = 0; i < passes.length; i++) {
      if (avance) avance(`Masquage des visages et plaques… ${i + 1}/${passes.length}`);
      vis = vis.concat(visagesDans(m, bmp, passes[i]));
      per = per.concat(personnesDans(m, bmp, passes[i]));
      pla = pla.concat(await plaquesDans(m, bmp, passes[i]));
    }
    vis = fusionner(vis); pla = fusionner(pla); per = fusionner(per);
    // Une personne sans visage reconnu : on masque sa tête (partie haute de la silhouette) plutôt que de la laisser visible.
    const tetes = per.filter((p) => !vis.some((v) => contient(p, v))).map((p) => ({ x: p.x, y: p.y, w: p.w, h: p.h * PART_TETE, score: p.score }));
    const k = Math.min(1, maxPx / Math.max(bmp.width, bmp.height)), c = toile(bmp.width * k, bmp.height * k), g = c.getContext('2d');
    g.drawImage(bmp, 0, 0, c.width, c.height);
    g.fillStyle = '#1b1b1b';
    const aplat = (b, marge) => { const mx = b.w * marge, my = b.h * marge; g.fillRect((b.x - mx) * k, (b.y - my) * k, (b.w + 2 * mx) * k, (b.h + 2 * my) * k); };
    vis.forEach((b) => aplat(b, MARGE_VISAGE)); tetes.forEach((b) => aplat(b, 0.1)); pla.forEach((b) => aplat(b, MARGE_PLAQUE));
    const blob = await new Promise((res) => c.toBlob(res, 'image/jpeg', qualite));
    return { statut: 'masque', blob, visages: vis.length, personnes: tetes.length, plaques: pla.length, boites: { visages: vis, personnes: tetes, plaques: pla } };
  } catch (e) { return { statut: 'indisponible', erreur: String(e && e.message || e) }; }
}
