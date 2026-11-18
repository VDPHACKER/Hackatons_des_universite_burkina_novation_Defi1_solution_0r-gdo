import { $, $$, esc, badge, motifsHtml, dateFr, appareil, localiser, raisonGps } from '../util.js';
import { qAdd } from '../db.js';
import { resultatsLocaux, fileComplete, synchroniser, nouvelleCle } from '../sync.js';
import { lireExif } from '../exif.js';
import { masquer, preparer } from '../masquage.js';
import { etat, get } from '../api.js';
import { pointsPossibles, distanceM, POINTS_CONFIRMATION, JOURS_MEME_LIEU } from '../fidelite.js';
import { t } from '../i18n.js';
import { icone } from '../icones.js';
import * as M from '../map.js';
import { commune } from '../commune.js';

const NB_PHOTOS = 5;                 // comme la configuration du serveur (verification.limites.photos_max)
const AUDIO_SECONDES = 60, AUDIO_OCTETS_MAX = 500000;
const radios = (nom, l) => l.map(([v, t]) => `<label><input type="radio" name="${nom}" value="${v}"> ${t}</label>`).join('');
const AIDE = { a_confirmer: 'Pour passer à « vérifié » (70/100 ou plus) il manque une photo ou une deuxième personne qui confirme.', verifie: 'Merci ! Le tas entre dans le plan de ramassage.', rejete: 'Un agent peut revoir ce signalement : rien n\'est supprimé.' };
// Deux façons de signaler, au choix dès le début : un formulaire court avec photo, ou un message vocal (pour qui lit peu).
const ORDRE = { formulaire: ['tas', 'photos', 'lieu'], voix: ['voix', 'photos', 'lieu'] };
const NOMS = { tas: t('sig.etape1', 'Le tas'), voix: t('sig.etape_voix', 'Votre message'), photos: t('sig.etape2', 'Photo'), lieu: t('sig.etape3', 'Lieu') };

export async function render(racine, params) {
  racine.innerHTML = `<h2>${t('sig.titre', "Signaler un tas d'ordures")}</h2>
  <p class="mut">Un signalement concerne <b>un tas</b>, jamais une personne. Sans réseau, il est gardé sur votre téléphone et part tout seul plus tard.</p>
  <div id="file" class="alerte info" hidden></div>
  <div id="choix-mode" class="choix-mode" role="group" aria-label="Comment voulez-vous signaler ?">
    <button type="button" class="carte mode" data-mode="formulaire">${icone('camera', 30)}<b>${t('sig.mode_form', 'Photo et quelques questions')}</b><small>${t('sig.mode_form2', 'Le plus fiable : environ 30 secondes.')}</small></button>
    <button type="button" class="carte mode" data-mode="voix">${icone('micro', 30)}<b>${t('sig.mode_voix', 'Message vocal')}</b><small>${t('sig.mode_voix2', 'Décrivez le tas en français, mooré ou dioula.')}</small></button>
  </div>
  <form id="f" novalidate hidden>
  <ol class="etapes" id="etapes" aria-label="Étapes du signalement"></ol>
  <section data-sec="tas" aria-label="Le tas" hidden>
    <fieldset><legend>${t('sig.taille', 'Taille estimée du tas')}</legend><div class="choix">${radios('taille', [['petit', icone('brouette', 22) + ' ' + t('sig.petit', 'Petit (une brouette)')], ['moyen', icone('tricycle', 22) + ' ' + t('sig.moyen', 'Moyen (un tricycle)')], ['grand', icone('camion', 22) + ' ' + t('sig.grand', 'Grand (un camion)')], ['tres_grand', icone('camion', 22) + icone('camion', 22) + ' ' + t('sig.tres_grand', 'Très grand')]])}</div>
      <p id="estimation" class="petit estimation" aria-live="polite" hidden></p></fieldset>
    <fieldset><legend>${t('sig.nature', 'Nature des déchets')}</legend><div class="choix">${[['menagers', t('sig.menagers', 'Ménagers')], ['plastiques', t('sig.plastiques', 'Plastiques')], ['gravats', t('sig.gravats', 'Gravats')], ['vegetaux', t('sig.vegetaux', 'Végétaux')], ['dangereux', t('sig.dangereux', 'Dangereux ou médicaux')]].map(([v, t]) => `<label><input type="checkbox" name="nature" value="${v}"> ${t}</label>`).join('')}</div></fieldset>
    <fieldset><legend>${t('sig.caniveau', 'Le tas bouche-t-il un caniveau ?')}</legend><div class="choix">${radios('caniveau', [['non', t('sig.non', 'Non')], ['oui', t('sig.oui', 'Oui')], ['nsp', t('sig.nsp', 'Je ne sais pas')]])}</div></fieldset>
    <fieldset id="q-acces"><legend>${t('sig.acces', 'Un camion peut-il y accéder ?')}</legend><div class="choix">${radios('acces', [['facile', t('sig.facile', 'Oui, facilement')], ['difficile', t('sig.difficile', 'Difficilement')], ['non', t('sig.non', 'Non')]])}</div></fieldset>
  </section>
  <section data-sec="voix" aria-label="Message vocal" hidden>
    <fieldset><legend>${t('sig.voix_titre2', 'Décrivez le tas et le lieu à voix haute')}</legend>
      <p class="petit mut">Taille du tas, ce qu'il contient, un repère pour le trouver (marché, école, mosquée, église…). ${AUDIO_SECONDES} secondes au plus, en français, en mooré ou en dioula. Votre voix n'est écoutée que par la brigade et elle est <b>effacée après 30 jours</b>.</p>
      <div class="choix"><button type="button" class="primaire" id="b-voix">${icone('micro', 20)} ${t('sig.enregistrer', 'Enregistrer un message')}</button><button type="button" class="secondaire" id="b-voix-sup" hidden>${t('sig.effacer', 'Effacer')}</button></div>
      <audio id="voix-lecteur" controls hidden></audio><p id="voix-etat" class="petit" role="status" aria-live="polite"></p>
    </fieldset>
  </section>
  <section data-sec="photos" aria-label="Photos" hidden>
    <fieldset><legend>${t('sig.photos', 'Photo du tas')} <small class="mut" id="photo-facultative" hidden>(facultative)</small></legend>
      <p class="petit mut">Photographiez le tas, pas les personnes : les visages et les plaques sont <b>masqués sur votre téléphone</b> avant l'envoi. ${t('sig.une_photo', 'Une seule photo suffit.')}</p>
      <div class="choix" id="ligne-sans-photo"><label><input type="checkbox" id="sans-photo"> ${t('sig.sans_photo', 'Je ne peux pas prendre de photo (moins fiable)')}</label></div>
      <div id="zone-photo" class="grille">
        ${Array.from({ length: NB_PHOTOS }, (_, k) => k + 1).map((n) => `<div${n > 2 ? ' class="photo-plus" hidden' : ''}><input id="p${n}" class="cache-fichier" type="file" accept="image/*" ${n === 1 ? 'capture="environment"' : ''}><label class="btn bouton-photo" for="p${n}">${icone('camera', 20)} ${t('sig.photo', 'Photo')} ${n}</label><div id="ap${n}" aria-live="polite"></div></div>`).join('')}
      </div>
      <button type="button" class="lien petit" id="plus-photos">${t('sig.plus_photos', 'Ajouter d\'autres photos')}</button>
    </fieldset>
  </section>
  <section data-sec="lieu" aria-label="Lieu" hidden>
    <fieldset><legend>${t('sig.lieu', 'Où est le tas ?')}</legend>
      <div class="choix"><button type="button" id="b-gps" class="primaire">${icone('locate', 20)} ${t('sig.gps', 'Utiliser ma position')}</button>
        <button type="button" id="b-gps-ok" class="secondaire" hidden>${t('sig.gps_ok', 'Utiliser cette position')}</button></div>
      <p id="gps-etat" class="petit" role="status" aria-live="polite">${t('sig.pos_non', 'Position non prise.')}</p>
      <div id="info-lieu" aria-live="polite"></div>
      <p class="petit mut">${t('sig.gps_conseil', 'Conseil : placez-vous à côté du tas, à l\'air libre, et attendez quelques secondes : la précision s\'améliore.')}</p>
      <button type="button" id="b-mini" class="secondaire">${icone('carte', 20)} ${t('sig.ajuster', 'Placer ou ajuster le point sur la carte')}</button>
      <div id="mini-carte" class="mini-carte" hidden><div id="mini-conteneur"></div><span class="epingle" aria-hidden="true"></span>
        <p class="petit mut">Faites glisser la carte : le tas est sous l'épingle.</p></div>
      <details><summary>Saisir la position à la main</summary><label for="lat">Latitude</label><input id="lat" type="text" inputmode="decimal"><label for="lon">Longitude</label><input id="lon" type="text" inputmode="decimal"></details>
    </fieldset>
  </section>
  <p id="erreur" class="alerte err" role="alert" hidden></p>
  <div class="choix navig"><button type="button" class="secondaire" id="retour">${t('sig.retour', 'Retour')}</button><button type="button" class="primaire" id="suivant">${t('sig.continuer', 'Continuer')}</button><button class="primaire" id="envoyer" type="submit" hidden>${t('sig.envoyer', 'Envoyer le signalement')}</button></div>
  </form><div id="res" aria-live="polite"></div><h3>Mes signalements</h3><div id="mes"></div>`;
  let pos = null, etape = 0, vivant = true, voix = null, mode = 'formulaire';
  const photos = [], exifs = [];
  const eco = document.body.classList.contains('eco');
  const ordre = () => ORDRE[mode];
  const montrer = (e) => {
    etape = e;
    const sec = ordre()[e];
    $$('section[data-sec]').forEach((s) => (s.hidden = s.dataset.sec !== sec));
    $('#etapes').innerHTML = ordre().map((n, i) => `<li data-e="${i}" class="${i < e ? 'fait' : ''}" ${i === e ? 'aria-current="step"' : ''}><b>${i + 1}</b><span>${NOMS[n]}</span></li>`).join('');
    $('#suivant').hidden = e === ordre().length - 1; $('#envoyer').hidden = e !== ordre().length - 1;
    $('#erreur').hidden = true; $('#f').scrollIntoView({ block: 'start' });
  };
  const choisirMode = (m) => {
    mode = m; $('#choix-mode').hidden = true; $('#f').hidden = false;
    $('#photo-facultative').hidden = mode !== 'voix'; $('#ligne-sans-photo').hidden = mode === 'voix';
    montrer(0);
  };
  $$('#choix-mode [data-mode]').forEach((b) => (b.onclick = () => choisirMode(b.dataset.mode)));
  const revenirAuChoix = () => { $('#f').hidden = true; $('#choix-mode').hidden = false; };
  const erreur = (m) => { const er = $('#erreur'); er.innerHTML = m.map(esc).join('<br>'); er.hidden = false; er.scrollIntoView({ block: 'center' }); };
  const verifier = (sec) => {
    const m = [];
    if (sec === 'tas' && !$('input[name=taille]:checked')) m.push(t('sig.err_taille', 'Choisissez la taille du tas.'));
    if (sec === 'voix' && !voix) m.push('Enregistrez votre message (bouton « Enregistrer un message »).');
    if (sec === 'photos' && mode === 'formulaire' && !$('#sans-photo').checked && !photos.filter(Boolean).length) m.push('Prenez une photo, ou cochez « Je ne peux pas prendre de photo ».');
    return m;
  };
  $('#suivant').onclick = () => { const m = verifier(ordre()[etape]); if (m.length) erreur(m); else montrer(etape + 1); };
  $('#retour').onclick = () => (etape === 0 ? revenirAuChoix() : montrer(etape - 1));
  $('#plus-photos').onclick = (e) => { $$('.photo-plus').forEach((d) => (d.hidden = false)); e.currentTarget.hidden = true; };
  // Petit tas (une brouette) : la question de l'accès d'un camion n'a pas de sens, on ne la pose pas.
  const majTaille = () => {
    const v = $('input[name=taille]:checked')?.value;
    $('#q-acces').hidden = v === 'petit';
    if (v === 'petit') $$('input[name=acces]').forEach((x) => (x.checked = false));
    const est = $('#estimation');
    if (v) { est.hidden = false; est.innerHTML = `${icone('points', 16)} Une fois vérifié, ce signalement peut vous rapporter <b>${pointsPossibles(v, false)} points</b>${v === 'petit' ? ' (un petit tas rapporte peu : signalez surtout les dépôts qui s\'accumulent)' : ''}.`; }
  };
  $$('input[name=taille]').forEach((x) => (x.onchange = majTaille));
  if (params && params.get('mode')) choisirMode(params.get('mode') === 'voix' ? 'voix' : 'formulaire');
  else if (params && params.get('lat')) choisirMode('formulaire');

  // --- position
  const etatGps = (texte, classe = '') => { const e = $('#gps-etat'); if (e) { e.textContent = texte; e.className = 'petit ' + classe; } };
  const majPos = (p, source = 'gps') => {
    pos = p; $('#lat').value = p.lat.toFixed(5); $('#lon').value = p.lon.toFixed(5); infoLieu(p);
    etatGps(source === 'carte' ? `Position placée sur la carte : ${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}.`
      : `Position prise : ${p.lat.toFixed(5)}, ${p.lon.toFixed(5)} (précision ${Math.round(p.precision)} m).${p.precision > 100 ? ' Peu précise : ajustez le point sur la carte si besoin.' : ''}`, p.precision > 100 && source !== 'carte' ? 'attention' : 'ok');
  };
  // Lieu déjà répertorié ? Déjà signalé par moi cette semaine ? On le dit tout de suite (et c'est pris en compte pour les points).
  let deja = false, infoN = 0;
  const infoLieu = async (p) => {
    const n = ++infoN, z = $('#info-lieu'); if (!z) return;
    let dep = null; try { dep = await get('/api/public/depotoirs'); } catch (e) { /* hors ligne sans copie : pas d'information */ }
    const proche = ((dep && dep.features) || []).map((f) => ({ d: distanceM(p, { lat: f.geometry.coordinates[1], lon: f.geometry.coordinates[0] }), f })).sort((a, b) => a.d - b.d)[0];
    const miens = (await resultatsLocaux()).filter((r) => r.lat != null && distanceM(p, r) <= 50 && Date.now() - (Date.parse(r.date || '') || 0) < JOURS_MEME_LIEU * 864e5);
    if (!vivant || n !== infoN || !$('#info-lieu')) return;
    deja = !!(proche && proche.d <= 80);
    const l = [];
    if (proche && proche.d <= 150) l.push(`<p class="alerte info petit">${icone('carte', 16)} Un dépotoir confirmé est déjà répertorié à environ <b>${Math.max(10, Math.round(proche.d / 10) * 10)} m</b>. Si c'est le même tas, votre signalement le confirme${deja ? ` (<b>${POINTS_CONFIRMATION} points</b> une fois vérifié)` : ''} ; si c'est un autre tas, continuez.</p>`);
    if (miens.length) l.push(`<p class="alerte attention petit">${icone('sablier', 16)} Vous avez déjà signalé ce lieu il y a moins de ${JOURS_MEME_LIEU} jours : un nouveau signalement n'apportera pas de points. Signalez-le seulement si le tas a grossi ou n'a pas été ramassé.</p>`);
    if (!l.length) l.push(`<p class="petit ok">${icone('coche', 16)} Aucun dépotoir connu ici : votre signalement peut en ajouter un nouveau sur la carte.</p>`);
    z.innerHTML = l.join('');
  };
  { const la = parseFloat(params && params.get('lat')), lo = parseFloat(params && params.get('lon')); if (!isNaN(la) && !isNaN(lo)) majPos({ lat: la, lon: lo, precision: parseFloat(params.get('prec')) || 30 }); }   // position venue de « Autour de moi »
  let arreterGps = null;
  const versPos = (r) => ({ lat: r.coords.latitude, lon: r.coords.longitude, precision: r.coords.accuracy });
  $('#b-gps').onclick = () => {
    if (arreterGps) arreterGps();
    const b = $('#b-gps'), ok = $('#b-gps-ok'); b.disabled = true;
    etatGps('Recherche de la position… (jusqu\'à 30 secondes)');
    arreterGps = localiser((r) => { arreterGps = null; if (!vivant) return; b.disabled = false; ok.hidden = true; majPos(versPos(r)); if (miniOuverte) recentrerMini(); },
      (e) => { arreterGps = null; if (!vivant) return; b.disabled = false; ok.hidden = true; etatGps(raisonGps(e), 'erreur'); },
      { progression: (r) => { if (!vivant) return; ok.hidden = false; etatGps(`Précision actuelle : ${Math.round(r.coords.accuracy)} m… on affine. Vous pouvez aussi utiliser cette position.`); } });
  };
  $('#b-gps-ok').onclick = () => { if (arreterGps) arreterGps(); };
  // Petite carte : le point est sous l'épingle centrale ; utile quand le GPS est imprécis ou indisponible.
  let miniOuverte = false;
  const recentrerMini = () => { const m = M.getMap(); if (m && pos) m.jumpTo({ center: [pos.lon, pos.lat], zoom: 17 }); };
  $('#b-mini').onclick = async () => {
    const z = $('#mini-carte'); miniOuverte = z.hidden; z.hidden = !miniOuverte;
    if (!miniOuverte) return;
    const m = await M.montrer($('#mini-conteneur'));
    if (!vivant) return;
    if (pos) recentrerMini(); else m.jumpTo({ center: commune().centre, zoom: 14 });
    m.resize();
    // Seul un déplacement fait par la personne compte (pas le recentrage automatique) : jamais de position inventée.
    const lire = (e) => { if (!e || !e.originalEvent || !miniOuverte || !vivant) return; const c = m.getCenter(); majPos({ lat: c.lat, lon: c.lng, precision: 15 }, 'carte'); };
    m.off('moveend', m.__oregdoMini || (() => {})); m.__oregdoMini = lire; m.on('moveend', lire);
  };

  // --- photos
  $('#sans-photo').onchange = (e) => ($('#zone-photo').hidden = e.target.checked);
  // Visages et plaques sont masqués SUR LE TÉLÉPHONE avant tout envoi. Sans masquage réussi, la photo n'est pas gardée.
  preparer().catch(() => {});                          // chargement anticipé : les modèles sont ensuite en cache hors ligne
  for (let n = 1; n <= NB_PHOTOS; n++) $('#p' + n).onchange = async (e) => {
    const f = e.target.files[0]; if (!f) return;
    const zone = $('#ap' + n); photos[n - 1] = exifs[n - 1] = undefined;
    zone.innerHTML = '<span class="petit mut" role="status">Masquage des visages et plaques…</span>';
    exifs[n - 1] = await lireExif(f);                  // lu sur l'original ; la photo masquée, elle, n'a plus d'EXIF
    const r = await masquer(f, { qualite: eco ? 0.5 : 0.7, maxPx: eco ? 640 : 1024, avance: (t) => vivant && (zone.firstChild.textContent = t) });
    if (!vivant) return;
    if (r.statut !== 'masque') {
      exifs[n - 1] = undefined; e.target.value = '';
      zone.innerHTML = '<span class="petit" style="color:var(--rej)" role="alert">Le masquage des visages et des plaques n\'a pas pu s\'exécuter : cette photo n\'est pas envoyée. Réessayez, ou cochez « Je ne peux pas prendre de photo ».</span>';
      return;
    }
    photos[n - 1] = r.blob;
    const im = new Image(); im.src = URL.createObjectURL(r.blob); im.alt = `Aperçu masqué de la photo ${n}`; im.style.cssText = 'height:90px;margin-top:6px;border-radius:8px;display:block';
    const nb = r.visages + r.personnes, bilan = document.createElement('span'); bilan.className = 'petit mut';
    bilan.textContent = (nb || r.plaques) ? `Masqué : ${nb} personne(s), ${r.plaques} plaque(s).` : 'Aucun visage ni plaque détecté.';
    zone.replaceChildren(im, bilan);
  };

  // --- message vocal (MediaRecorder : WebM/Opus sur Android, MP4 sur iPhone)
  let rec = null, minuteur = null;
  const dire = (t) => { const z = $('#voix-etat'); if (z) z.textContent = t; };
  const afficherVoix = () => {
    $('#voix-lecteur').hidden = !voix; $('#b-voix-sup').hidden = !voix;
    if (voix) $('#voix-lecteur').src = URL.createObjectURL(voix); else $('#voix-lecteur').removeAttribute('src');
    $('#b-voix').innerHTML = icone('micro', 20) + ' ' + (voix ? t('sig.reenregistrer', 'Réenregistrer') : t('sig.enregistrer', 'Enregistrer un message'));
  };
  $('#b-voix').onclick = async () => {
    if (rec && rec.state === 'recording') { rec.stop(); return; }
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { dire(window.isSecureContext ? 'Le message vocal n\'est pas disponible sur ce navigateur : vous pouvez ignorer cette étape.' : 'Le micro est bloqué sur une adresse non sécurisée (http) : ouvrez l\'application en https, ou ignorez cette étape.'); return; }
    let flux;
    try { flux = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch (e) { dire('Autorisez le microphone pour enregistrer un message, ou ignorez cette étape.'); return; }
    const mime = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4'].find((m) => MediaRecorder.isTypeSupported(m));
    rec = new MediaRecorder(flux, { ...(mime ? { mimeType: mime } : {}), audioBitsPerSecond: 24000 });
    const morceaux = [];
    rec.ondataavailable = (e) => e.data.size && morceaux.push(e.data);
    rec.onstop = () => {
      clearInterval(minuteur); flux.getTracks().forEach((t) => t.stop());
      const b = new Blob(morceaux, { type: rec.mimeType });
      if (b.size > AUDIO_OCTETS_MAX) { voix = null; dire('Message trop long : recommencez en moins d\'une minute.'); }
      else { voix = b; dire(`Message enregistré (${Math.round(b.size / 1000)} Ko). Écoutez-le, ou réenregistrez.`); }
      afficherVoix(); $('#b-voix').disabled = false;
    };
    rec.start(); let reste = AUDIO_SECONDES;
    $('#b-voix').innerHTML = icone('stop', 20) + ' ' + t('sig.arreter', 'Arrêter'); dire(`Enregistrement… ${reste} s`);
    minuteur = setInterval(() => { reste -= 1; dire(`Enregistrement… ${reste} s`); if (reste <= 0 && rec.state === 'recording') rec.stop(); }, 1000);
  };
  $('#b-voix-sup').onclick = () => { voix = null; dire('Message effacé.'); afficherVoix(); };

  // --- mes signalements
  const listeMes = async () => {
    if (!vivant || !$('#mes')) return;
    const [l, att] = [await resultatsLocaux(), await fileComplete()];
    const enAtt = att.map((it) => `<div class="carte"><b>${icone('sablier', 16)} En attente d'envoi</b> <span class="mut petit">(${esc(dateFr(it.rapport.date_client))})</span><br>${it.derniere_erreur ? `<span class="petit">Problème technique : ${esc(it.derniere_erreur)} Votre signalement est conservé sur ce téléphone, essai n° ${it.essais || 0}.</span>` : '<span class="petit">Il partira dès que le réseau revient.</span>'}</div>`).join('');
    $('#mes').innerHTML = enAtt + (l.map((r) => `<div class="carte"><b>Signalement ${esc(r.code_suivi || r.id)}</b> ${badge(r.statut)} ${r.score != null ? '· ' + esc(Math.round(r.score)) + '/100' : ''}<p class="petit">${esc(AIDE[r.statut] || '')}${r.code_suivi ? ` <a href="#/suivi?code=${encodeURIComponent(r.code_suivi)}">Voir l'état actuel</a>` : ''}</p>${r.motifs ? motifsHtml(r.motifs) : ''}</div>`).join('') || (att.length ? '' : '<p class="mut">Aucun signalement envoyé depuis ce téléphone.</p>'));
    const n = att.length; const fl = $('#file'); fl.hidden = !n;
    fl.innerHTML = `<b>${n} signalement(s) en attente d'envoi.</b> ${etat.online ? '<button class="secondaire" id="b-sync" type="button">Réessayer maintenant</button>' : 'Ils partiront dès le retour du réseau.'}`;
    $('#b-sync')?.addEventListener('click', async () => { await synchroniser(); listeMes(); });
  };

  // --- envoi
  $('#f').onsubmit = async (e) => {
    e.preventDefault(); $('#res').innerHTML = '';
    const lat = parseFloat(($('#lat').value || '').replace(',', '.')), lon = parseFloat(($('#lon').value || '').replace(',', '.'));
    const sans = $('#sans-photo').checked;
    for (const k of [0, 1]) { const m = verifier(k); if (m.length) { montrer(k); erreur(m); return; } }
    if (isNaN(lat) || isNaN(lon)) { erreur(['Indiquez la position (bouton « Utiliser ma position »).']); return; }
    const taille = mode === 'formulaire' ? $('input[name=taille]:checked')?.value || null : null;
    const rapport = { lat, lon, precision_m: pos?.precision ?? null, taille, nature: $$('input[name=nature]:checked').map((x) => x.value), caniveau: $('input[name=caniveau]:checked')?.value || 'nsp', accessible: taille === 'petit' || mode === 'voix' ? null : $('input[name=acces]:checked')?.value || 'difficile', deja_repertorie: deja, mode, sans_photo: sans, exif: exifs.filter(Boolean), date_client: new Date().toISOString(), appareil: appareil() };
    const bl = sans ? [] : photos.filter(Boolean), message = voix;
    // Hors ligne d'abord : le signalement est enregistré sur le téléphone TOUT DE SUITE (aucune attente du réseau),
    // puis envoyé en arrière-plan. La clé évite tout doublon si l'envoi est répété après une coupure.
    rapport.cle = nouvelleCle();
    await qAdd({ rapport, photos: bl, audio: message || undefined, essais: 0, derniere_erreur: '' });
    $('#res').innerHTML = `<div class="alerte info" id="etat-envoi"><b>${t('sig.enregistre', 'Enregistré sur ce téléphone.')}</b> ${navigator.onLine ? 'Envoi en cours…' : 'Pas de réseau : il partira automatiquement dès que le réseau revient.'}</div>`;
    $('#f').reset(); photos.length = exifs.length = 0; voix = null; afficherVoix(); dire('');
    for (let n = 1; n <= NB_PHOTOS; n++) $('#ap' + n).innerHTML = '';
    $('#zone-photo').hidden = false; $('#gps-etat').textContent = t('sig.pos_non', 'Position non prise.'); pos = null; deja = false;
    $('#info-lieu').innerHTML = ''; $('#estimation').hidden = true; $('#q-acces').hidden = false; montrer(0); revenirAuChoix();
    await listeMes(); $('#res').scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (!navigator.onLine) return;
    await synchroniser();
    if (!vivant) return;
    const r = (await resultatsLocaux()).find((x) => x.cle === rapport.cle), z = $('#res');
    if (!z) return;
    if (!r) {
      const it = (await fileComplete()).find((x) => x.rapport.cle === rapport.cle);
      z.innerHTML = `<div class="alerte info"><b>Enregistré sur ce téléphone.</b> ${it && it.derniere_erreur ? 'Envoi pas encore réussi (' + esc(it.derniere_erreur) + '). ' : ''}Il sera renvoyé automatiquement, sans doublon.</div>`;
      return;
    }
    // Citoyen (sans compte) : code de suivi seulement. Agent connecté : score et motifs.
    z.innerHTML = r.score == null
      ? `<div class="carte"><h3>${t('merci', 'Merci')} ! ${t('sig.recu', 'Signalement reçu')}</h3>${badge(r.statut)}<p>${esc(AIDE[r.statut] || '')} La mairie vérifie, puis planifie le ramassage.</p><p>${t('sig.code', 'Votre code de suivi')} : <b style="font-size:1.3rem">${esc(r.code_suivi)}</b><br><span class="petit mut">Notez-le : il permet de voir où en est le signalement, sans nom ni compte.</span></p><a class="btn" href="#/suivi?code=${encodeURIComponent(r.code_suivi)}">Suivre ce signalement</a></div>`
      : `<div class="carte"><h3>Merci ! Signalement ${esc(r.code_suivi || r.id)} reçu</h3>${badge(r.statut)} Score ${esc(Math.round(r.score))}/100<p>${esc(AIDE[r.statut] || '')} La mairie vérifie, puis planifie le ramassage.</p>${motifsHtml(r.motifs)}</div>`;
    listeMes();
  };
  listeMes();
  const h = () => listeMes(); window.addEventListener('oregdo:sync', h);
  return () => {
    vivant = false; if (rec && rec.state === 'recording') rec.stop(); window.removeEventListener('oregdo:sync', h);
    if (arreterGps) arreterGps();
    const m = M.getMap(); if (m && m.__oregdoMini) { m.off('moveend', m.__oregdoMini); m.__oregdoMini = null; }
  };
}
