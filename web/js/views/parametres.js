import { $, $$, esc, nf, toast, erreurTexte } from '../util.js';
import { post } from '../api.js';
import { LANGUES, langue, choisir, statut } from '../i18n.js';
import { commune } from '../commune.js';
import { utilisateur, LIBELLE_ROLE } from '../session.js';

export async function render(racine) {
  const c = commune(), u = utilisateur(), admin = !!u && u.role === 'admin';       // le jargon technique ne s'affiche qu'à l'administration
  racine.innerHTML = `<h2>Paramètres</h2>
  <div class="carte"><h3 style="margin-top:0">Langue</h3>
    <div class="choix" role="radiogroup" aria-label="Langue de l'application">${Object.entries(LANGUES).map(([k, n]) => `<label><input type="radio" name="lg" value="${k}" ${k === langue() ? 'checked' : ''}> ${esc(n)}</label>`).join('')}</div>
    <p class="petit mut">${statut() === 'brouillon' ? 'Les textes en dioula et en mooré sont des brouillons en cours de validation : tout texte non traduit reste en français.' : 'Les textes non traduits restent en français.'}${admin ? ' Pour compléter les traductions : <code>docs/14-langues-locales.md</code>.' : ''}</p></div>
  <div class="carte"><h3 style="margin-top:0">Affichage</h3>
    <div class="choix"><button class="secondaire" id="p-theme">Thème clair ou sombre</button><button class="secondaire" id="p-eco">Mode économie de données</button></div>
    <p class="petit mut">Le mode économie réduit la taille des photos et masque le fond de carte pour consommer moins de données mobiles.</p></div>
  <div class="carte"><h3 style="margin-top:0">Commune</h3>
    <p><b>${esc(c.nom)}</b> · ${nf(c.population)} habitants (RGPH 2019) · ${nf(c.menages)} ménages</p>
    <p class="petit mut">Application : ${esc(c.marque || '')}.${admin ? ' La commune servie se choisit au démarrage du serveur (variable <code>OREGDO_COMMUNE</code>) ; voir <code>docs/15-seconde-commune.md</code>.' : ''}</p>
    ${u && ['mairie', 'admin'].includes(u.role) ? '<p><button class="secondaire" id="p-relire" type="button">Relire le fichier de paramètres</button></p><p class="petit mut" id="p-relire-etat" role="status">Après une modification de <code>commune_config.yaml</code> : le scénario revient aux valeurs du fichier, sans redémarrer le serveur. Un fichier invalide est refusé et l\'ancien reste en place.</p>' : ''}</div>
  <div class="carte"><h3 style="margin-top:0">Compte</h3>
    ${u ? `<p><b>${esc(u.nom)}</b> · ${esc(LIBELLE_ROLE[u.role] || u.role)}${u.zone ? ' · ' + esc(u.zone) : ''}</p>` : '<p>Vous utilisez l\'application sans compte (citoyen). <a href="#/connexion">Connexion des agents et de la mairie</a></p>'}</div>`;
  $$('input[name=lg]').forEach((r) => (r.onchange = () => choisir(r.value)));
  $('#p-theme').onclick = () => document.getElementById('btn-theme').click();
  $('#p-eco').onclick = () => document.getElementById('btn-eco').click();
  const relire = $('#p-relire');
  if (relire) relire.onclick = async () => {
    relire.disabled = true;
    try { const r = await post('/api/config/recharger'); $('#p-relire-etat').textContent = r.message; toast(r.message); }
    catch (e) { $('#p-relire-etat').textContent = erreurTexte(e); }
    relire.disabled = false;
  };
}
