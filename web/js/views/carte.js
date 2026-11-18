import { commune } from '../commune.js';
import { $, $$, esc, badge, motifsHtml, normList, waLink, nf, toast, dateFr, appareil, localiser, raisonGps } from '../util.js';
import { get, post, lirePlan } from '../api.js';
import * as M from '../map.js';
import { role } from '../session.js';
import { destine } from '../acces.js';
import { t } from '../i18n.js';
import { icone, symbole } from '../icones.js';

let clicsOk = false;
const toFC = (l) => ({ type: 'FeatureCollection', features: l.filter((s) => s.lat != null).map((s) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [+s.lon, +s.lat] }, properties: { id: s.id, statut: s.statut, score: s.score, taille: s.taille, secteur: s.secteur, date: s.horodatage || s.date || s.recu_le, motifs: JSON.stringify(s.motifs || []) } })) });

// « Moi aussi je le vois » / « Ce tas n'est plus là » : demande le GPS de l'appareil, le serveur vérifie qu'on est à moins de 150 m.
function donnerAvis(ref, type, bouton) {
  const etat = $('#fiche [data-avis-etat]'), dire = (t, err) => { if (etat) { etat.textContent = t; etat.style.color = err ? 'var(--rej, #c4202a)' : ''; } };
  if (!navigator.geolocation) { dire('Le GPS n\'est pas disponible sur cet appareil.', true); return; }
  bouton.disabled = true; dire('Recherche de votre position…');
  localiser(async (pos) => {
    try {
      const r = await post(`/api/public/depotoirs/${encodeURIComponent(ref)}/avis`, { type, appareil: appareil(), lat: pos.coords.latitude, lon: pos.coords.longitude });
      dire(r.message);
    } catch (e) { dire(e.message || 'Avis impossible pour le moment.', true); bouton.disabled = false; }
  }, (e) => { dire(raisonGps(e), true); bouton.disabled = false; });
}

export function ficheHtml(p, lon, lat) {
  const motifs = (() => { try { return JSON.parse(p.motifs || '[]'); } catch (e) { return []; } })();
  const txt = `Dépotoir ${p.statut === 'verifie' ? 'vérifié' : 'signalé'} à ${commune().nom} (Orẽgdo) : https://www.openstreetmap.org/?mlat=${(+lat).toFixed(5)}&mlon=${(+lon).toFixed(5)}#map=18/${(+lat).toFixed(5)}/${(+lon).toFixed(5)}`;
  return `<h3>Signalement ${esc(p.id)} ${badge(p.statut)}</h3>
  <p>Score : <b>${nf(p.score)}/100</b>${p.secteur ? ' · ' + esc(p.secteur) : ''}${p.taille ? ' · Taille : ' + esc(p.taille) : ''} · ${esc(dateFr(p.date))}</p>
  <h4>Pourquoi ce statut ?</h4>${motifsHtml(motifs)}
  <p><a class="btn primaire" target="_blank" rel="noopener" href="${waLink(txt)}">Partager sur WhatsApp</a>
  ${p.statut === 'a_confirmer' && ['brigade', 'admin'].includes(role()) ? `<a class="btn" href="#/verifier?id=${encodeURIComponent(p.id)}">Revalider (agents)</a>` : ''}
  <button class="secondaire" data-fermer>Fermer</button></p>`;
}

export async function render(racine, params) {
  racine.innerHTML = `<div class="carte-zone"><div class="cible" id="cible-carte" aria-label="Carte des dépotoirs de ${commune().nom}. La même information existe sous forme de liste avec le bouton Liste." role="application"></div>
  <div class="barre-carte"><button id="b-filtres" aria-expanded="false" aria-controls="panneau">${icone('filtres', 18)} Filtres</button><button id="b-liste" aria-pressed="false">${icone('liste', 18)} Liste</button><button id="b-autour" class="primaire">${icone('locate', 18)} Autour de moi</button></div>
  <div class="panneau-filtres" id="panneau" role="group" aria-label="Filtres de la carte" hidden>
    <p class="petit"><b>Statut des signalements</b></p>
    <div class="puces-f"><button data-f="verifie" aria-pressed="true">${icone('coche', 16)} Vérifiés</button><button data-f="a_confirmer" aria-pressed="true">? À confirmer</button><button data-f="rejete" aria-pressed="false">${icone('croix', 16)} Rejetés</button></div>
    <p class="petit"><b>Calques (à activer)</b></p>
    <div class="puces-f"><button data-l="pr" aria-pressed="false">Points de regroupement</button><button data-l="tournees" aria-pressed="false">Tournées</button><button data-l="rues" aria-pressed="true">Rues</button><button data-l="reperes" aria-pressed="true">Repères</button><button data-l="quartiers" aria-pressed="true">Quartiers</button><button data-l="communes" aria-pressed="true">Communes</button><button data-l="decharges" aria-pressed="true">Décharges déjà dans OSM</button><button data-l="secteurs" aria-pressed="false" title="Découpage de démonstration, pas les secteurs officiels">Secteurs (démo)</button><button data-l="osm" class="noeco" aria-pressed="false">Fond OSM en ligne</button></div>
  </div>
  <details class="legende" id="legende" open></details>
  ${destine('signaler', role()) ? `<a class="cta-flottant" href="#/signaler">${icone('plus', 18)} Signaler un tas</a>` : ''}
  <div class="fiche" id="fiche" hidden role="dialog" aria-label="Détail"></div></div>
  <div class="liste-carte" id="liste" hidden></div>`;
  let vivant = true, statuts = ['verifie', 'a_confirmer'], sigs = [], depFC = null, prFC = null;
  const map = await M.montrer($('#cible-carte'));
  if (!vivant || !$('#fiche')) return;
  const fiche = $('#fiche');
  const ouvrir = (html) => { const f = $('#fiche'); if (!f) return; f.innerHTML = html; f.hidden = false; $('[data-fermer]', f)?.addEventListener('click', () => (f.hidden = true)); };
  if (!clicsOk) {
    clicsOk = true;
    M.cliquer('sig', (f) => { const c = f.geometry.coordinates; window.__ouvrir?.(ficheHtml(f.properties, c[0], c[1])); });
    M.cliquer('dep', (f) => {
      const p = f.properties;
      const detail = p.id == null ? `Niveau de confiance : <b>${p.niveau_confiance === 'eleve' ? 'élevé' : 'moyen'}</b> (position arrondie à environ 100 m).` : `${nf(p.nb_signalements)} signalement(s) regroupés · confiance ${nf(p.confiance <= 1 ? p.confiance * 100 : p.confiance)} %.`;
      const avis = p.ref ? `<p class="petit"><b>${nf(p.confirmations)}</b> personne(s) confirment ce tas${p.disparu ? ` · <b>${nf(p.disparu)}</b> disent qu'il n'est plus là` : ''}.</p>
        <p class="petit mut">Vous êtes à côté de ce tas ? Dites-le : plus de voisins confirment, plus il est sûr. Votre position GPS est vérifiée (moins de 150 m), elle n'est pas conservée.</p>
        <div class="choix"><button class="primaire" data-avis="present">${t('carte.present', 'Je suis sur place : je le vois aussi')}</button><button class="secondaire" data-avis="disparu">${t('carte.disparu', "Ce tas n'est plus là")}</button></div>
        <p data-avis-etat class="petit" role="status" aria-live="polite"></p>` : '';
      window.__ouvrir?.(`<h3>Dépotoir ${p.id == null ? '' : esc(p.id)} ${badge('verifie')}</h3><p>${detail}</p>${avis}<button class="secondaire" data-fermer>Fermer</button>`);
      $$('#fiche [data-avis]').forEach((b) => (b.onclick = () => donnerAvis(p.ref, b.dataset.avis, b)));
    });
    M.cliquer('pr', (f) => window.__ouvrir?.(`<h3>Point de regroupement ${esc(f.properties.id)}</h3><p>${f.properties.secteur ? 'Secteur ' + esc(f.properties.secteur) + ' · ' : ''}coût d'installation ${nf(f.properties.cout_fcfa)} FCFA.</p><button class="secondaire" data-fermer>Fermer</button>`));
    M.cliquer('cet', (f) => window.__ouvrir?.(`<h3>${esc(f.properties.nom)}</h3><p class="mut">Position à confirmer avec la mairie.</p><button class="secondaire" data-fermer>Fermer</button>`));
  }
  window.__ouvrir = ouvrir;

  // --- Autour de moi : le point de regroupement et le dépotoir confirmé les plus proches (distances à vol d'oiseau)
  const dist = (a, b) => { const r = Math.PI / 180, dLa = (b[1] - a[1]) * r, dLo = (b[0] - a[0]) * r;
    const h = Math.sin(dLa / 2) ** 2 + Math.cos(a[1] * r) * Math.cos(b[1] * r) * Math.sin(dLo / 2) ** 2; return 12742000 * Math.asin(Math.sqrt(h)); };
  const proche = (col, p) => { let b = null; for (const f of ((col && col.features) || [])) { const c = f.geometry.coordinates, d = dist(p, c); if (!b || d < b.d) b = { d, f, c }; } return b; };
  const metres = (d) => (d < 950 ? `${nf(Math.round(d / 10) * 10)} m` : `${nf(d / 1000, 1)} km`);
  $('#b-autour').onclick = () => {
    ouvrir('<p class="mut" id="autour-etat">Recherche de votre position…</p>');
    localiser((pos) => {
      if (!vivant || !$('#fiche')) return;
      const p = [pos.coords.longitude, pos.coords.latitude], pr = proche(prFC, p), dp = proche(depFC, p);
      if (!map.getSource('moi')) { map.addSource('moi', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } }); map.addLayer({ id: 'moi', type: 'circle', source: 'moi', paint: { 'circle-radius': 7, 'circle-color': '#1565d8', 'circle-stroke-width': 3, 'circle-stroke-color': '#fff' } }); }
      map.getSource('moi').setData({ type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: p }, properties: {} }] });
      map.flyTo({ center: p, zoom: Math.max(map.getZoom(), 15), duration: 700 });
      ouvrir(`<h3>Autour de vous</h3>
        <p>${pr ? `${symbole('pr', 18)} <b>Point de regroupement le plus proche</b> : ${esc(pr.f.properties.id)}, à <b>${metres(pr.d)}</b> (environ ${Math.max(1, Math.round(pr.d / 75))} min à pied).` : 'Aucun point de regroupement connu près de vous.'}</p>
        <p>${dp ? `${symbole('depot', 18)} <b>Dépotoir confirmé le plus proche</b> : à ${metres(dp.d)}.` : 'Aucun dépotoir confirmé connu.'}</p>
        <p class="petit mut">Distances à vol d'oiseau, position non conservée. Vous voyez un tas qui n'est pas sur la carte ?</p>
        <p class="petit mut">Position à ${Math.round(pos.coords.accuracy)} m près.</p>
        <div class="choix">${destine('signaler', role()) ? `<a class="btn primaire" href="#/signaler?lat=${p[1].toFixed(6)}&lon=${p[0].toFixed(6)}&prec=${Math.round(pos.coords.accuracy)}">${icone('plus', 18)} Signaler un tas ici</a>` : ''}${pr ? `<button class="secondaire" id="b-voir-pr">Voir ce point</button>` : ''}<button class="secondaire" data-fermer>Fermer</button></div>`);
      $('#b-voir-pr')?.addEventListener('click', () => map.flyTo({ center: pr.c, zoom: 16.5, duration: 600 }));
    }, (e) => ouvrir(`<p role="alert">${esc(raisonGps(e))}</p><button class="secondaire" data-fermer>Fermer</button>`),
    { precisionVoulue: 60, dureeMax: 15000, progression: (r) => { const z = $('#autour-etat'); if (z) z.textContent = `Précision actuelle : ${Math.round(r.coords.accuracy)} m… on affine.`; } });
  };
  const personnel = ['brigade', 'mairie', 'admin'].includes(role());
  M.visible(['sites', 'avant', 'tournees'], false); M.visible(['pr'], !personnel); M.visible(['sig', 'dep'], true);
  $('.panneau-filtres [data-l="pr"]')?.setAttribute('aria-pressed', String(!personnel));
  const LEG = personnel ? [['depot', 'Dépotoir confirmé'], ['verifie', 'Signalement vérifié'], ['confirmer', 'À confirmer'], ['rejete', 'Rejeté'], ['pr', 'Point de regroupement'], ['cet', "Centre d'enfouissement"], ['camion', "Tournée d'un camion"]]
    : [['depot', 'Dépotoir confirmé : signalé et vérifié'], ['pr', 'Point de regroupement : où déposer ses déchets'], ['cet', "Centre d'enfouissement"]];
  $('#legende').innerHTML = '<summary style="font-weight:700;cursor:pointer">Légende</summary>' + LEG.map(([k, n]) => `<div>${symbole(k, 16)} ${n}</div>`).join(''); M.visible(M.GROUPES.secteurs, false); M.filtrerStatuts(statuts);
  if (matchMedia('(max-width:600px)').matches) $('#legende').open = false;
  $('#b-filtres').onclick = (e) => { const p = $('#panneau'); p.hidden = !p.hidden; e.currentTarget.setAttribute('aria-expanded', String(!p.hidden)); };
  const liste = () => {
    const l = $('#liste'); if (!l) return;
    const v = sigs.filter((s) => statuts.includes(s.statut));
    l.innerHTML = `<h2>${v.length} signalement(s)</h2>` + (v.slice(0, 80).map((s) => `<div class="carte"><b>${esc(s.id)}</b> ${badge(s.statut)} · ${nf(s.score)}/100 · ${esc(s.secteur || '')}<br>${motifsHtml((s.motifs || []).slice(0, 3))}</div>`).join('') || '<p class="mut">Aucun signalement pour ces filtres.</p>');
  };
  $$('.panneau-filtres [data-f]').forEach((b) => (b.onclick = () => {
    const s = b.dataset.f; statuts = statuts.includes(s) ? statuts.filter((x) => x !== s) : [...statuts, s];
    b.setAttribute('aria-pressed', statuts.includes(s)); M.filtrerStatuts(statuts); liste();
  }));
  $$('.panneau-filtres [data-l]').forEach((b) => (b.onclick = () => {
    const on = b.getAttribute('aria-pressed') !== 'true'; b.setAttribute('aria-pressed', on);
    const l = b.dataset.l;
    if (l === 'osm') { if (!navigator.onLine) { toast('Hors ligne : fond OSM indisponible.'); b.setAttribute('aria-pressed', false); return; } M.fond(on); }
    else M.visible(M.GROUPES[l] || [l], on);
  }));
  $('#b-liste').onclick = (e) => {
    const on = e.currentTarget.getAttribute('aria-pressed') !== 'true'; e.currentTarget.setAttribute('aria-pressed', on);
    const z = $('.carte-zone'); $('#liste').hidden = !on; z.style.height = on ? '40vh' : ''; z.style.flex = on ? 'none' : ''; if (on) liste(); map.resize();
  };
  try {
    // Droits : signalements complets (avec motifs) pour la brigade, la mairie et l'administration ; dépotoirs vérifiés pour les autres
    // comptes ; carte publique (positions arrondies, sans identifiant) pour le citoyen.
    const r = role();
    if (['brigade', 'mairie', 'admin'].includes(r)) { sigs = normList(await get('/api/signalements')); if (!vivant || !$('#fiche')) return; M.donnees('sig', toFC(sigs)); }
    else { $$('.panneau-filtres [data-f]').forEach((b) => (b.hidden = true)); statuts = []; }
    depFC = await get(r ? '/api/depotoirs' : '/api/public/depotoirs'); M.donnees('dep', depFC);
    const p = lirePlan(await get('/api/plan')); prFC = p.pr; M.donnees('pr', p.pr); M.donnees('tournees', p.tournees);
    if (params.get('id')) { const s = sigs.find((x) => String(x.id) === params.get('id')); if (s) M.centrer(s.lon, s.lat, 16); }
  } catch (e) { toast('Données indisponibles : ' + e.message); }
  return () => { vivant = false; window.__ouvrir = null; };
}
