// Portail du pré-collecteur : un acteur de terrain, sur téléphone, souvent sans réseau.
// Les collectes saisies hors ligne restent sur le téléphone (rattachées au compte) puis partent seules ; une clé évite tout doublon au renvoi.
import { $, $$, esc, nf, erreurTexte, toast } from '../util.js';
import { get, post } from '../api.js';
import { utilisateur } from '../session.js';
import { kvGet, kvSet } from '../db.js';
import { icone } from '../icones.js';
import { t } from '../i18n.js';

const CLE_ATTENTE = 'collectes_attente';
const aujourdhui = () => new Date().toLocaleDateString('sv-SE');           // AAAA-MM-JJ, jour local
const jourMoins = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return d.toLocaleDateString('sv-SE'); };
const nouvelleCle = () => 'c-' + (crypto.randomUUID ? crypto.randomUUID() : Date.now() + '-' + Math.random().toString(36).slice(2, 10));
const kpi = (cls, ico, valeur, lib, sous, unite = '') => `<div class="kpi-t ${cls}"><span class="rond">${icone(ico, 26)}</span><div><b>${esc(valeur)}${unite ? `<span class="unite">${esc(unite)}</span>` : ''}</b><span class="lib">${esc(lib)}</span><small>${esc(sous || '')}</small></div></div>`;

async function enAttente(id) { return ((await kvGet(CLE_ATTENTE)) || []).filter((x) => x.utilisateur === id); }

// Envoie les collectes en attente DE CE COMPTE. S'arrête à la première coupure réseau ; une erreur de validation sort l'élément (il ne pourrait jamais passer).
export async function envoyerAttente(id) {
  let envoyees = 0;
  for (const c of await enAttente(id)) {
    try { await post('/api/precollecteur/collectes', { kg: c.kg, nb_menages: c.nb_menages, date: c.date, cle_client: c.cle }); envoyees++; }
    catch (e) {
      // Seule une donnée refusée comme invalide (400, 422) est abandonnée : elle ne passerait jamais. Tout le reste est une panne ou un
      // problème de session (réseau, serveur, 401 session expirée, 403, 429 trop de requêtes) : la collecte reste sur le téléphone.
      if (e.status !== 400 && e.status !== 422) break;
    }
    const toutes = ((await kvGet(CLE_ATTENTE)) || []).filter((x) => x.cle !== c.cle);
    await kvSet(CLE_ATTENTE, toutes);
  }
  return envoyees;
}

export async function render(racine) {
  const u = utilisateur();
  racine.innerHTML = `<h2>${esc(t('pre.titre', 'Ma tournée'))}</h2>
  <p class="mut">${esc(u.nom)}${u.zone ? ' · ' + esc(u.zone) : ''} · ${esc(t('pre.point', 'point de regroupement'))} : <b>${esc(u.point || t('pre.nonrattache', 'non rattaché'))}</b></p>
  <div class="kpis" id="kpis" aria-live="polite"></div>
  <p id="attente" class="alerte info" role="status" hidden></p>
  <div class="pan" style="margin-top:14px"><h3>${esc(t('pre.saisir', 'Enregistrer une collecte'))}</h3>
  <form id="f" novalidate>
    <label for="kg">${esc(t('pre.kg', 'Poids ramassé (kg)'))}</label>
    <input id="kg" type="number" inputmode="decimal" min="1" max="5000" step="any" required style="font-size:1.6rem;font-weight:700">
    <div class="puces-rapides" id="rapides" role="group" aria-label="${esc(t('pre.rapide', 'Poids courants'))}">${[25, 50, 100, 200].map((k) => `<button type="button" class="secondaire" data-kg="${k}">${k} kg</button>`).join('')}</div>
    <label for="men">${esc(t('pre.menages', 'Ménages servis'))}</label>
    <div class="pas"><button type="button" class="secondaire" id="moins" aria-label="${esc(t('pre.moins', 'Un ménage de moins'))}">−</button>
      <input id="men" type="number" inputmode="numeric" min="0" max="2000" step="1" value="0"><button type="button" class="secondaire" id="plus" aria-label="${esc(t('pre.plus', 'Un ménage de plus'))}">+</button></div>
    <label for="date">${esc(t('pre.date', 'Date'))}</label><input id="date" type="date" max="${aujourdhui()}" value="${aujourdhui()}">
    <p id="erreur" class="alerte err" role="alert" hidden></p>
    <button class="primaire" type="submit" style="width:100%;margin-top:10px">${esc(t('pre.enregistrer', 'Enregistrer'))}</button>
  </form></div>
  <div class="pan" style="margin-top:14px"><h3>${esc(t('pre.semaine', 'Les 7 derniers jours'))}</h3><div id="semaine"></div></div>
  <div id="camion" aria-live="polite" style="margin-top:14px"></div>
  <div class="pan" style="margin-top:14px"><h3>${esc(t('pre.historique', 'Mes collectes'))}</h3><div id="liste" aria-live="polite"></div></div>`;
  let vivant = true, collectes = [];
  const ok = (s) => vivant && $(s);

  const dessiner = async () => {
    const att = await enAttente(u.identifiant);
    const lignes = [...att.map((a) => ({ date: a.date, kg: a.kg, nb_menages: a.nb_menages, point: u.point, attente: true })), ...collectes];
    const auj = aujourdhui(), dep = jourMoins(6);
    const jour = lignes.filter((c) => c.date === auj), sem = lignes.filter((c) => c.date >= dep);
    const somme = (l, k) => l.reduce((s, c) => s + (+c[k] || 0), 0);
    if (!ok('#kpis')) return;
    $('#kpis').innerHTML = kpi('bleu', 'brouette', nf(somme(jour, 'kg'), 1), t('pre.aujourdhui', 'Aujourd\'hui'), jour.length + ' ' + t('pre.collectes', 'collecte(s)'), 'kg') +
      kpi('vert', 'liste', nf(somme(sem, 'kg'), 1), t('pre.sur7', 'Sur 7 jours'), nf(somme(sem, 'nb_menages')) + ' ' + t('pre.menagesmin', 'ménages servis'), 'kg');
    const a = $('#attente'); a.hidden = !att.length;
    if (att.length) a.textContent = t('pre.attente', '{n} collecte(s) enregistrée(s) sur ce téléphone, en attente d\'envoi. Elles partiront dès que le réseau revient.', { n: att.length });
    // 7 jours en barres (les jours sans collecte restent visibles, à zéro)
    const jours = [...Array(7)].map((_, i) => jourMoins(6 - i)), kgJ = jours.map((j) => somme(lignes.filter((c) => c.date === j), 'kg')), max = Math.max(...kgJ, 1);
    $('#semaine').innerHTML = `<div class="barres" role="img" aria-label="${esc(t('pre.grapheAlt', 'Poids ramassé par jour sur 7 jours'))}">${kgJ.map((v, i) => `<div class="grp"><div class="b" style="height:${v ? Math.max(4, v / max * 100).toFixed(0) : 2}%;background:var(--pri);opacity:${v ? 1 : .25}" title="${esc(jours[i])} : ${esc(nf(v, 1))} kg"></div></div>`).join('')}</div>
      <div class="noms">${jours.map((j) => `<span>${esc(new Date(j + 'T12:00').toLocaleDateString('fr-FR', { weekday: 'short' }))}</span>`).join('')}</div>`;
    $('#liste').innerHTML = lignes.length
      ? `<div class="defile"><table><tr><th>${esc(t('pre.date', 'Date'))}</th><th>${esc(t('pre.poids', 'Poids'))}</th><th>${esc(t('pre.menagesCol', 'Ménages'))}</th><th></th></tr>${lignes.slice(0, 30).map((c) => `<tr><td>${esc(c.date)}</td><td>${esc(nf(c.kg, 1))} kg</td><td>${esc(c.nb_menages)}</td><td>${c.attente ? `<span class="petit mut">${esc(t('pre.enattente', 'en attente'))}</span>` : ''}</td></tr>`).join('')}</table></div>`
      : `<p class="mut">${esc(t('pre.aucune', 'Aucune collecte enregistrée.'))}</p>`;
  };
  const charger = async () => {
    try { collectes = (await get('/api/precollecteur/collectes')).collectes; } catch (e) { /* hors ligne : on garde ce qu'on a */ }
    await dessiner();
  };
  const camion = async () => {
    try {
      const r = await get('/api/precollecteur/tournee');
      if (!ok('#camion')) return;
      const feats = r.tournee?.features || [];
      $('#camion').innerHTML = `<div class="pan"><h3>${esc(t('pre.camions', 'Passages de camion'))}</h3><p>${esc(r.message)}</p>${feats.length
        ? `<ul>${feats.map((f) => `<li>${esc(t('pre.camion', 'Camion'))} ${esc(f.properties.camion + 1)}, voyage ${esc(f.properties.voyage)} · ${esc(nf(f.properties.distance_km, 1))} km · ${esc(nf(f.properties.charge_kg))} kg</li>`).join('')}</ul>` : ''}</div>`;
    } catch (e) { if (ok('#camion')) $('#camion').innerHTML = `<div class="pan"><p class="mut">${esc(t('pre.camionhl', 'Les passages de camion s\'affichent quand le réseau est disponible.'))}</p></div>`; }
  };

  $$('#rapides [data-kg]').forEach((b) => (b.onclick = () => { $('#kg').value = b.dataset.kg; $('#kg').focus(); }));
  $('#moins').onclick = () => { $('#men').value = Math.max(0, (+$('#men').value || 0) - 1); };
  $('#plus').onclick = () => { $('#men').value = Math.min(2000, (+$('#men').value || 0) + 1); };
  $('#f').onsubmit = async (e) => {
    e.preventDefault();
    const er = $('#erreur'); er.hidden = true;
    const kg = parseFloat(String($('#kg').value).replace(',', '.'));
    if (!(kg > 0) || kg > 5000) { er.textContent = t('pre.errkg', 'Indiquez le poids ramassé (plus de 0 et au plus 5 000 kg).'); er.hidden = false; return; }
    const c = { cle: nouvelleCle(), utilisateur: u.identifiant, kg, nb_menages: +$('#men').value || 0, date: $('#date').value || aujourdhui() };
    try {
      await post('/api/precollecteur/collectes', { kg: c.kg, nb_menages: c.nb_menages, date: c.date, cle_client: c.cle });
      toast(t('pre.ok', 'Collecte enregistrée.'));
    } catch (err) {
      if (err.status === 0) {                      // pas de réseau (ou délai dépassé) : on garde sur le téléphone ; la clé protège d'un double envoi
        await kvSet(CLE_ATTENTE, [...((await kvGet(CLE_ATTENTE)) || []), c]);
        toast(t('pre.gardee', 'Pas de réseau : collecte gardée sur ce téléphone, envoi automatique plus tard.'));
      } else { er.textContent = erreurTexte(err); er.hidden = false; return; }
    }
    $('#kg').value = ''; $('#men').value = '0';
    await charger();
  };
  const reprise = async () => { if (await envoyerAttente(u.identifiant)) { toast(t('pre.envoyees', 'Collectes en attente envoyées.')); } await charger(); };
  window.addEventListener('online', reprise);
  const timer = setInterval(() => { if (navigator.onLine) reprise(); }, 60000);
  dessiner(); reprise(); camion();                  // l'écran s'affiche tout de suite avec ce qui est sur le téléphone ; le réseau complète ensuite
  return () => { vivant = false; clearInterval(timer); window.removeEventListener('online', reprise); };
}
