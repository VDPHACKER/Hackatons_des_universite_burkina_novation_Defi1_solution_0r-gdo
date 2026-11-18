// Importer un fichier de collecte (brigade, mairie) : campagne de terrain, export ODK/KoboToolbox, couche d'un logiciel SIG,
// jeu de test du jury. Chaque ligne passe par les mêmes contrôles qu'un signalement fait dans l'application.
import { $, esc, erreurTexte, toast, badge } from '../util.js';
import { televerser } from '../api.js';
import { icone } from '../icones.js';

export async function render(racine) {
  racine.innerHTML = `<h2>Importer une collecte</h2>
  <p class="mut">Un fichier de signalements collectés sur le terrain passe par les mêmes contrôles qu'un signalement fait dans l'application. Une ligne incorrecte est refusée avec son explication ; le reste est traité.</p>
  <form id="imp" class="carte" novalidate>
    <label for="fichier">Fichier CSV ou GeoJSON</label>
    <input id="fichier" type="file" accept=".csv,.tsv,.txt,.geojson,.json,text/csv,application/geo+json,application/json">
    <button class="primaire" type="submit" id="b-imp">${icone('liste', 18)} Importer</button>
  </form>
  <div id="bilan" aria-live="polite"></div>
  <details class="pan"><summary>Formats acceptés</summary>
    <ul class="petit">
      <li><b>CSV</b> : colonnes <code>lat</code> et <code>lon</code> (ou <code>latitude</code>, <code>longitude</code>), séparateur virgule, point-virgule ou tabulation, virgule décimale acceptée. Facultatif : <code>secteur</code>, <code>horodatage</code>, <code>taille</code>, <code>nature</code>, <code>enqueteur</code>.</li>
      <li><b>Export brut d'ODK ou de KoboToolbox</b> : colonne <code>geopoint</code> ou <code>_geolocation</code>.</li>
      <li><b>Logiciel SIG</b> (QGIS…) : colonne de géométrie <code>WKT</code>, ou GeoJSON de points, multipoints ou surfaces (un tas cartographié comme une zone devient un point à l'intérieur).</li>
      <li>Sans photo, un signalement ne dépasse pas « à confirmer » : un agent doit passer. Maximum 5 000 lignes et 5 Mo.</li>
    </ul>
  </details>`;
  let vivant = true;
  $('#imp').onsubmit = async (e) => {
    e.preventDefault();
    const f = $('#fichier').files[0], z = $('#bilan'), b = $('#b-imp');
    if (!f) { z.innerHTML = '<p class="alerte err" role="alert">Choisissez un fichier.</p>'; return; }
    z.innerHTML = '<p class="mut">Import en cours…</p>'; b.disabled = true;
    try {
      const r = await televerser('/api/signalements/import', f);
      if (!vivant) return;
      const acc = r.acceptees || [], ref = r.refusees || [];
      const parStatut = (s) => acc.filter((x) => x.statut === s).length;
      z.innerHTML = `<div class="carte"><h3>${esc(r.nb_acceptees)} ligne(s) lue(s), ${esc(r.nb_refusees)} refusée(s)</h3>
        ${r.erreur_fichier ? `<p class="alerte err" role="alert">${esc(r.erreur_fichier)}</p>` : ''}
        ${acc.length ? `<p>${badge('verifie')} ${parStatut('verifie')} &nbsp; ${badge('a_confirmer')} ${parStatut('a_confirmer')} &nbsp; ${badge('rejete')} ${parStatut('rejete')}</p>
          <p class="petit mut">Les signalements rejetés restent enregistrés avec leur motif (visible dans « À vérifier »), mais n'entrent jamais dans le plan.</p>` : ''}
        ${ref.length ? `<details open><summary>Lignes refusées et pourquoi</summary><div class="defile"><table><tr><th>Ligne</th><th>Raison</th></tr>${ref.slice(0, 50).map((x) => `<tr><td>${esc(x.ligne)}</td><td>${esc(x.raison)}</td></tr>`).join('')}</table></div></details>` : ''}</div>`;
      toast('Import terminé.');
    } catch (er) { if (vivant) z.innerHTML = `<p class="alerte err" role="alert">${esc(erreurTexte(er))}</p>`; }
    if (vivant) b.disabled = false;
  };
  return () => { vivant = false; };
}
