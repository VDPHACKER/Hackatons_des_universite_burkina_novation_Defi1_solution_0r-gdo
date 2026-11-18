import { $, $$, esc, nf, erreurTexte, toast } from '../util.js';
import { get, post } from '../api.js';
import { icone } from '../icones.js';

const aujourdhui = () => new Date().toLocaleDateString('sv-SE');

export async function render(racine) {
  racine.innerHTML = `<h2>Interventions de la brigade</h2>
  <div class="kpis compact" id="kpis" aria-live="polite"></div>
  <details class="alerte info regle" id="regles"><summary><b>Deux phases : sensibiliser, puis sanctionner</b></summary><p>D'abord la <b>sensibilisation</b> des habitants. La <b>sanction</b> n'est possible qu'après, sur un dépotoir <b>vérifié</b>, avec un numéro de procès-verbal (sauf flagrant délit motivé).</p></details>
  <div class="filtres" id="filtres" role="group" aria-label="Filtrer les dépotoirs"></div>
  <div id="liste" aria-live="polite"><p class="mut">Chargement…</p></div>`;
  let vivant = true, bareme = null, tous = [], filtre = 'tous', enFile = null;
  const FILTRES = [['tous', 'Tous'], ['revoir', 'À revérifier'], ['sans', 'Sans sensibilisation'], ['sanction', 'Sanction possible']];
  const garde = { tous: () => true, revoir: (d) => d.a_reverifier, sans: (d) => d.interventions.sensibilisation === 0, sanction: (d) => d.sanction_possible };
  const kpi = (cls, ico, v, lib, sous) => `<div class="kpi-t ${cls}"><span class="rond">${icone(ico, 26)}</span><div><b>${esc(v)}</b><span class="lib">${esc(lib)}</span><small>${esc(sous)}</small></div></div>`;
  const ok = () => vivant && $('#liste');
  const formulaire = (d) => {
    const z = $(`[data-form="${d.id}"]`); if (!z) return; z.hidden = false;
    z.innerHTML = `<label for="t-${d.id}">Type d'intervention</label>
      <select id="t-${d.id}"><option value="sensibilisation">Sensibilisation des habitants</option><option value="sanction">Sanction (procès-verbal)</option></select>
      <label for="i-${d.id}">Issue (ce qui s'est passé)</label><input id="i-${d.id}" type="text" maxlength="500" placeholder="Ex. voisins informés, tas à enlever sous 48 h">
      <div data-sanction hidden>
        <label for="pv-${d.id}">Numéro du procès-verbal (obligatoire)</label><input id="pv-${d.id}" type="text" maxlength="60">
        <label for="m-${d.id}">Montant (FCFA)</label><input id="m-${d.id}" type="number" step="1000" inputmode="numeric">
        <p class="petit mut" data-bareme></p>
        <label class="choix"><input type="checkbox" id="fl-${d.id}"> Flagrant délit (sanction sans sensibilisation préalable)</label>
        <div data-flagrant hidden><label for="mf-${d.id}">Motif du flagrant délit</label><input id="mf-${d.id}" type="text" maxlength="500"></div>
      </div>
      <label for="dt-${d.id}">Date</label><input id="dt-${d.id}" type="date" max="${aujourdhui()}" value="${aujourdhui()}">
      <p class="alerte err" data-err role="alert" hidden></p>
      <div class="choix"><button class="primaire" data-ok>Enregistrer</button><button class="secondaire" data-annuler>Annuler</button></div>`;
    const type = $('#t-' + d.id), san = $('[data-sanction]', z), fl = $('#fl-' + d.id);
    const maj = () => {
      const s = type.value === 'sanction'; san.hidden = !s;
      $('[data-flagrant]', z).hidden = !fl.checked;
      if (s && bareme) {
        const rec = d.interventions.sanction > 0, m = rec ? bareme.recidive_multiplicateur : 1;
        const mini = bareme.amende_min_fcfa * m, maxi = bareme.amende_max_fcfa * m;
        $('[data-bareme]', z).textContent = `Barème : ${nf(mini)} à ${nf(maxi)} FCFA${rec ? ' (récidive : montant doublé)' : ''}. ${bareme.base_legale}.`;
        const champ = $('#m-' + d.id); if (!champ.value) champ.value = mini;
      }
    };
    type.onchange = maj; fl.onchange = maj; maj();
    $('[data-annuler]', z).onclick = () => { z.hidden = true; z.innerHTML = ''; };
    $('[data-ok]', z).onclick = async (e) => {
      const er = $('[data-err]', z); er.hidden = true;
      const corps = { depotoir_id: d.id, type: type.value, issue: $('#i-' + d.id).value.trim() || undefined, date: $('#dt-' + d.id).value || undefined };
      if (type.value === 'sanction') {
        Object.assign(corps, { numero_pv: $('#pv-' + d.id).value.trim(), montant_fcfa: $('#m-' + d.id).value ? +$('#m-' + d.id).value : undefined, flagrant_delit: fl.checked, motif_flagrant: fl.checked ? $('#mf-' + d.id).value.trim() : undefined });
      }
      e.target.disabled = true;
      try { await post('/api/brigade/interventions', corps); toast('Intervention enregistrée.'); charger(); }
      catch (err) { er.textContent = erreurTexte(err); er.hidden = false; e.target.disabled = false; }
    };
  };
  const charger = async () => {
    try {
      [bareme] = await Promise.all([get('/api/brigade/bareme').catch(() => null)]);
      const r = await get('/api/brigade/depotoirs');
      if (!ok()) return;
      tous = r.depotoirs;                                     // ordre du serveur : tas signalés « disparus » d'abord, puis par confiance
      try { enFile = (await get('/api/brigade/file')).nombre; } catch (e) { enFile = enFile ?? null; }
      dessiner();
    } catch (e) { if ($('#liste')) $('#liste').innerHTML = `<p class="alerte err" role="alert">${esc(erreurTexte(e))}</p>`; }
  };
  const dessiner = () => {
    if (!ok()) return;
    $('#kpis').innerHTML = kpi('orange', 'alerte', tous.filter(garde.revoir).length, 'À revérifier', 'voisins : « plus là »') +
      kpi('bleu', 'ampoule', enFile ?? '–', 'À vérifier', 'signalements en attente') +
      kpi('vert', 'liste', tous.filter(garde.sans).length, 'Sans passage', 'première sensibilisation');
    $('#filtres').innerHTML = FILTRES.map(([k, n]) => `<button type="button" class="${k === filtre ? 'actif' : ''}" aria-pressed="${k === filtre}" data-f="${k}">${esc(n)} <span class="petit">${tous.filter(garde[k]).length}</span></button>`).join('');
    $$('#filtres [data-f]').forEach((b) => (b.onclick = () => { filtre = b.dataset.f; nAff = 15; dessiner(); }));
    {
      const l = tous.filter(garde[filtre]);
      $('#liste').innerHTML = l.length
        ? l.slice(0, nAff).map((d) => `<article class="carte"><h3>Dépotoir ${esc(d.id)} · confiance ${esc(nf(d.confiance))}/100</h3>
          ${d.a_reverifier ? `<p class="alerte err" role="alert"><b>À revérifier :</b> ${esc(d.avis_disparu)} voisins (appareils distincts) disent que ce tas n'est plus là. Allez voir sur place ; rien n'est supprimé tant qu'un agent ne l'a pas constaté.</p>` : ''}
          <p class="petit mut">${esc(d.nb_enqueteurs)} personne(s) distincte(s) l'ont signalé${d.avis_present ? ` dont ${esc(d.avis_present)} voisin(s) sur place` : ''} · <a href="#/carte?id=${esc(d.id)}">Voir sur la carte</a> · <a href="geo:${esc(d.lat)},${esc(d.lon)}?q=${esc(d.lat)},${esc(d.lon)}" title="Ouvre l'application de cartes du téléphone">Y aller</a></p>
          <p>Sensibilisations : <b>${esc(d.interventions.sensibilisation)}</b> · Sanctions : <b>${esc(d.interventions.sanction)}</b> ${d.sanction_possible ? '' : '<span class="petit mut">(sanction possible après une sensibilisation)</span>'}</p>
          <button class="secondaire" data-ouvrir="${esc(d.id)}">Enregistrer une intervention…</button><div data-form="${esc(d.id)}" hidden></div></article>`).join('')
          + (l.length > nAff ? `<p class="voir-plus"><button class="secondaire" id="plus-l">Afficher ${Math.min(15, l.length - nAff)} de plus (${l.length - nAff} restant(s))</button></p>` : '')
        : `<p class="alerte info">${tous.length ? 'Aucun dépotoir ne correspond à ce filtre.' : 'Aucun dépotoir vérifié pour le moment. Les signalements « à confirmer » sont dans l\'écran « À vérifier ».'}</p>`;
      $$('[data-ouvrir]').forEach((b) => (b.onclick = () => formulaire(l.find((x) => String(x.id) === b.dataset.ouvrir))));
      $('#plus-l')?.addEventListener('click', () => { nAff += 15; dessiner(); });
    }
  };
  let nAff = 15;                                              // par pages de 15 : la liste reste légère sur un téléphone
  charger();
  return () => { vivant = false; };
}
