import { $, $$, esc, badge, motifsHtml, normList, toast, dateFr, erreurTexte } from '../util.js';
import { get, post } from '../api.js';
import { kvGet, kvSet } from '../db.js';
import { utilisateur, jeton } from '../session.js';
import { icone } from '../icones.js';

const MOTIFS = ['Vérifié sur place par un agent', 'Photo et lieu concordent', 'Tas déjà évacué', 'Lieu introuvable', 'Fausse alerte probable'];
const date = (s) => dateFr(s.horodatage || s.date || s.recu_le);
const PAGE = 15;

export async function render(racine, params) {
  racine.innerHTML = `<h2>Vérification par les agents</h2>
  <p class="mut">Agents de la commune ou de la brigade Laabal : confirmez ou rejetez un signalement. Rien n'est jamais supprimé, tout est inscrit au journal. Seuil : <b>70/100 et plus = vérifié</b>, 40 à 69 = à confirmer, moins de 40 = rejeté.</p>
  <p class="petit mut">Vous revalidez en tant que <b>${esc(utilisateur().nom)}</b> : votre nom est inscrit au journal.</p>
  <div class="choix" id="onglets-v">${[['a_confirmer', 'À confirmer'], ['verifie', 'Vérifiés'], ['rejete', 'Rejetés']].map(([v, t], i) => `<label><input type="radio" name="st" value="${v}" ${i === 0 ? 'checked' : ''}> ${t}</label>`).join('')}</div>
  <div id="liste" aria-live="polite"></div>
  <h3>Journal des revalidations (cet appareil)</h3><div id="journal"></div>`;
  let st = 'a_confirmer', vivant = true; const focus = params.get('id');
  const journal = async () => {
    const j = (await kvGet('journal')) || []; if (!vivant || !$('#journal')) return;
    $('#journal').innerHTML = j.length ? `<div class="defile"><table><tr><th>Date</th><th>Signalement</th><th>Changement</th><th>Agent</th><th>Motif</th></tr>${j.map((x) => `<tr><td>${esc(dateFr(x.date))}</td><td>${esc(x.id)}</td><td>${esc(x.avant)} → ${esc(x.apres)}</td><td>${esc(x.agent)}</td><td>${esc(x.motif)}</td></tr>`).join('')}</table></div>` : '<p class="mut">Aucune revalidation pour le moment.</p>';
  };
  const charger = async () => {
    $('#liste').innerHTML = '<p class="mut">Chargement…</p>';
    try {
      const l = normList(await get('/api/brigade/file?statut=' + st));
      if (!vivant || !$('#liste')) return;
      // Par pages de 15 : une liste de plusieurs centaines de cartes rend le téléphone lent et la page interminable.
      let nAff = PAGE;
      const iFocus = focus ? l.findIndex((x) => String(x.id) === focus) : -1;
      if (iFocus >= nAff) nAff = iFocus + 1;
      const rendre = () => {
      const vus = l.slice(0, nAff);
      $('#liste').innerHTML = vus.length ? vus.map((s) => `<article class="carte" id="s-${esc(s.id)}" ${String(s.id) === focus ? 'style="border-color:var(--foc);border-width:4px"' : ''}>
        <h3>Signalement ${esc(s.id)} ${badge(s.statut)} · ${esc(Math.round(s.score))}/100</h3>
        <p class="petit mut">${esc(s.secteur || 'Secteur inconnu')} · ${esc(date(s))} · <a href="#/carte?id=${encodeURIComponent(s.id)}">Voir sur la carte</a></p>
        ${s.statut === 'a_confirmer' ? `<p class="petit">Il manque ${esc(Math.max(1, Math.ceil(70 - s.score)))} point(s) pour être « vérifié » : une photo ou une confirmation d'une autre personne, ou la décision d'un agent.</p>` : ''}
        <details class="motifs"><summary>Pourquoi ${esc(Math.round(s.score))}/100 ? (${esc((s.motifs || []).length)} contrôle(s))</summary>${motifsHtml(s.motifs)}</details>
        ${s.a_audio ? `<p><button class="secondaire" data-voix="${esc(s.id)}">${icone('volume', 18)} Écouter le message vocal</button> <audio data-lecteur="${esc(s.id)}" controls hidden></audio><span class="petit mut" data-voix-etat="${esc(s.id)}"></span></p>` : ''}
        <button class="secondaire" data-ouvrir="${esc(s.id)}">Revalider…</button><div data-form="${esc(s.id)}" hidden></div></article>`).join('')
        + (l.length > nAff ? `<p class="voir-plus"><button class="secondaire" id="plus-l">Afficher ${Math.min(PAGE, l.length - nAff)} de plus (${l.length - nAff} restant(s))</button></p>` : '')
        : '<p class="alerte info">Aucun signalement dans cette catégorie. Bon travail.</p>';
      $('#plus-l')?.addEventListener('click', () => { nAff += PAGE; rendre(); });
      $$('[data-ouvrir]').forEach((b) => (b.onclick = () => formulaire(b.dataset.ouvrir, l.find((x) => String(x.id) === b.dataset.ouvrir))));
      // Message vocal : donnée personnelle, servie par l'API authentifiée (brigade), jamais par une adresse publique.
      $$('[data-voix]').forEach((b) => (b.onclick = async () => {
        const id = b.dataset.voix, lecteur = $(`[data-lecteur="${CSS.escape(id)}"]`), etatVoix = $(`[data-voix-etat="${CSS.escape(id)}"]`);
        b.disabled = true; etatVoix.textContent = ' Chargement…';
        try {
          const rep = await fetch(`/api/brigade/audio/${encodeURIComponent(id)}`, { headers: { Authorization: 'Bearer ' + jeton() } });
          if (!rep.ok) throw new Error(rep.status === 404 ? 'Message effacé ou absent.' : `Erreur ${rep.status}`);
          lecteur.src = URL.createObjectURL(await rep.blob()); lecteur.hidden = false; etatVoix.textContent = ''; lecteur.play().catch(() => {});
        } catch (e) { etatVoix.textContent = ' ' + e.message; }
        b.disabled = false;
      }));
      };
      rendre();
      if (focus && $('#s-' + CSS.escape(focus))) { $('#s-' + CSS.escape(focus)).scrollIntoView(); formulaire(focus, l.find((x) => String(x.id) === focus)); }
    } catch (e) { if ($('#liste')) $('#liste').innerHTML = `<p class="alerte err">${esc(erreurTexte(e))}</p>`; }
  };
  const formulaire = (id, s) => {
    const z = $(`[data-form="${CSS.escape(id)}"]`); if (!z) return; z.hidden = false;
    z.innerHTML = `<label for="mo-${id}">Motif (obligatoire)</label><input id="mo-${id}" type="text" list="dl-m" placeholder="Ex. vérifié sur place"><datalist id="dl-m">${MOTIFS.map((m) => `<option value="${esc(m)}">`).join('')}</datalist>
      <p class="alerte err" hidden data-err role="alert"></p>
      <div class="choix"><button class="primaire" data-d="verifie">Confirmer (vérifié)</button><button class="danger" data-d="rejete">Rejeter</button><button class="secondaire" data-d="a_confirmer">Remettre à confirmer</button></div>`;
    $$('[data-d]', z).forEach((b) => (b.onclick = async () => {
      const agent = utilisateur().identifiant, motif = $('#mo-' + CSS.escape(id)).value.trim(), er = $('[data-err]', z);
      if (motif.length < 5) { er.textContent = 'Indiquez un motif d’au moins 5 lettres.'; er.hidden = false; return; }
      b.disabled = true;
      try {
        await post(`/api/signalements/${encodeURIComponent(id)}/revalider`, { statut: b.dataset.d, motif });
        const j = (await kvGet('journal')) || []; j.unshift({ id, avant: s?.statut, apres: b.dataset.d, agent, motif, date: new Date().toISOString() }); await kvSet('journal', j.slice(0, 100));
        toast('Revalidation enregistrée dans le journal.'); journal(); charger();
      } catch (e) { er.textContent = erreurTexte(e); er.hidden = false; b.disabled = false; }
    }));
  };
  $$('input[name=st]').forEach((r) => (r.onchange = () => { st = r.value; charger(); }));
  journal(); charger();
  return () => { vivant = false; };
}
