import { $, esc, nf, download, toast, fc } from '../util.js';
import { get } from '../api.js';
import { autorise } from '../session.js';

function versOsm(g) {
  let id = -1;
  const n = fc(g).features.filter((f) => f.geometry?.type === 'Point').map((f) => {
    const t = { landuse: 'landfill', informal: 'yes', source: 'Orẽgdo', ...(f.properties || {}) };
    ['id', 'statut', 'confiance', 'nb_signalements', 'taille', 'score', 'motifs'].forEach((k) => delete t[k]);
    const tags = Object.entries(t).map(([k, v]) => `<tag k="${esc(k)}" v="${esc(v)}"/>`).join('');
    return `<node id="${id--}" action="modify" visible="true" lat="${f.geometry.coordinates[1]}" lon="${f.geometry.coordinates[0]}">${tags}</node>`;
  });
  return `<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6" generator="Orẽgdo">\n${n.join('\n')}\n</osm>\n`;
}
export async function render(racine) {
  racine.innerHTML = `<h2>Bien commun</h2>
  <p>Orẽgdo est un outil libre. Les dépotoirs vérifiés peuvent être versés dans OpenStreetMap pour que chacun, partout, profite de la carte.</p>
  <h3>Export vers OpenStreetMap</h3>
  <div class="alerte"><b>Avant de verser dans OSM :</b> discutez avec la communauté OSM locale. Ne versez que des objets vérifiés. Les balises viennent de la configuration de la commune.</div>
  ${autorise(['mairie']) ? `<button class="primaire" id="b-exp">Préparer l'export</button>` : `<p class="alerte info">L'export est réservé à la mairie. <a href="#/connexion?retour=commun">Se connecter</a></p>`}<div id="exp" aria-live="polite"></div>
  <h3>Licences</h3><ul><li><b>Code : AGPLv3</b> (si vous l'hébergez et le modifiez, partagez vos changements).</li><li><b>Données : ODbL</b> (comme OpenStreetMap : citer « © contributeurs OpenStreetMap » et partager à l'identique).</li><li>Carte : MapLibre GL JS (licence BSD 3 clauses), copiée dans <code>web/vendor/</code>.</li></ul>
  <p class="petit mut">Les données de démonstration sont <b>synthétiques</b> et ne doivent jamais être versées dans OSM.</p>
  <h3>Répliquer pour une autre commune</h3>
  <ol><li>Lancez <code>python scripts/creer_pack_commune.py</code> avec le nom, le centre, la population officielle (RGPH) et le nombre de secteurs de la commune : il crée <code>packs/&lt;code&gt;</code> depuis OpenStreetMap et Open Buildings.</li><li>Lancez <code>python scripts/build_osm_layers.py --commune &lt;code&gt;</code> pour le graphe routier et le fond de carte.</li><li>Démarrez avec <code>OREGDO_COMMUNE=&lt;code&gt;</code> : l'interface s'adapte. Bobo-Dioulasso a été créée ainsi (docs/15).</li></ol>`;
  const exporter = async (demo) => {
    $('#exp').innerHTML = '<p class="mut">Préparation…</p>';
    try {
      const r = await get('/api/export/osm' + (demo ? '?demo=1' : ''));
      const g = r.geojson || (r.type === 'FeatureCollection' ? r : null);
      const osm = typeof r.osm === 'string' ? r.osm : g ? versOsm(g) : null;
      const n = fc(g).features.length;
      $('#exp').innerHTML = `<div class="carte"><b>${nf(n)} dépotoir(s) vérifié(s)</b> prêts à l'export.${demo ? '<p class="alerte err"><b>Fichier de démonstration :</b> données synthétiques, à ne jamais verser dans OpenStreetMap (chaque objet le dit dans sa balise <code>note</code>).</p>' : ''}<div class="choix" style="margin-top:8px"><button class="secondaire" id="d-geo">Télécharger .geojson</button><button class="secondaire" id="d-osm">Télécharger .osm (JOSM)</button></div></div>`;
      $('#d-geo').onclick = () => download(demo ? 'DEMO-depotoirs.geojson' : 'depotoirs-verifies.geojson', JSON.stringify(g, null, 1));
      $('#d-osm').onclick = () => (osm ? download(demo ? 'DEMO-depotoirs.osm' : 'depotoirs-verifies.osm', osm, 'application/xml') : toast('Format .osm indisponible.'));
    } catch (er) {
      // 409 : tous les dépotoirs vérifiés sont synthétiques. On le dit, et on propose seulement un fichier de démonstration marqué.
      $('#exp').innerHTML = `<p class="alerte err" role="alert">${esc(er.message)}</p>${er.status === 409 ? '<button class="secondaire" id="b-demo">Préparer un fichier de démonstration (marqué)</button>' : ''}`;
      $('#b-demo')?.addEventListener('click', () => exporter(true));
    }
  };
  $('#b-exp')?.addEventListener('click', (e) => { e.target.disabled = true; exporter(false).finally(() => (e.target.disabled = false)); });
}
