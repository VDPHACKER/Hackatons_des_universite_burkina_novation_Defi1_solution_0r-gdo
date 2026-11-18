import { $, $$, esc, nf, dateFr, erreurTexte, toast } from '../util.js';
import { get, post, appel } from '../api.js';
import { LIBELLE_ROLE, utilisateur } from '../session.js';

const ROLES = ['precollecteur', 'brigade', 'mairie', 'admin'];

export async function render(racine) {
  racine.innerHTML = `<h2>Administration</h2>
  <div class="choix"><a class="btn primaire" href="#/jury">Console du jury (épreuve en direct)</a></div>
  <h3>État de la base</h3><div id="etat" aria-live="polite"><p class="mut">Chargement…</p></div>
  <h3>Données de démonstration</h3>
  <p class="mut petit">Le jeu de démonstration est entièrement <b>synthétique</b> (signalements piégés générés). Il sert aux essais et à la soutenance ; il est marqué comme tel partout. Le retirer ne touche jamais aux vrais signalements.</p>
  <div class="choix"><button class="secondaire" id="b-charger">Charger la démonstration</button><button class="danger" id="b-retirer">Retirer la démonstration</button></div>
  <p id="demo-msg" role="status" class="petit"></p>
  <h3>Comptes</h3><div id="comptes"></div>
  <details class="carte"><summary><b>Créer un compte</b></summary>
    <form id="nouveau" novalidate>
      <label for="n-id">Identifiant (3 à 40 caractères : lettres, chiffres, . - _)</label><input id="n-id" autocomplete="off" autocapitalize="none">
      <label for="n-nom">Nom complet</label><input id="n-nom" autocomplete="off">
      <label for="n-role">Rôle</label><select id="n-role">${ROLES.map((r) => `<option value="${r}">${esc(LIBELLE_ROLE[r])}</option>`).join('')}</select>
      <label for="n-zone">Zone ou secteur (facultatif)</label><input id="n-zone" autocomplete="off">
      <label for="n-point">Point de regroupement (pré-collecteur)</label><input id="n-point" autocomplete="off" placeholder="Ex. un identifiant de PR du plan">
      <label for="n-mdp">Mot de passe initial (8 caractères minimum)</label><input id="n-mdp" type="password" autocomplete="new-password">
      <p id="n-err" class="alerte err" role="alert" hidden></p>
      <button class="primaire" type="submit">Créer</button>
    </form></details>
  <h3>Journal d'audit (30 derniers événements)</h3><div id="audit"></div>`;
  let vivant = true;
  const ok = (id) => vivant && $(id);
  const moi = utilisateur().identifiant;

  const etat = async () => {
    try {
      const e = await get('/api/admin/etat');
      if (!ok('#etat')) return;
      $('#etat').innerHTML = `<div class="grille"><div class="kpi"><span>Signalements</span><b>${nf(e.nb_signalements)}</b><small class="mut">dont ${nf(e.nb_synthetiques)} synthétiques, ${nf(e.nb_essais)} d'essai</small></div>
        <div class="kpi"><span>Comptes</span><b>${nf(e.nb_utilisateurs)}</b></div>
        <div class="kpi"><span>Clé de signature</span><b style="font-size:.95rem">${esc(e.secret_source)}</b></div></div>
        ${e.base_vide ? '<p class="alerte info">La base est vide : les signalements réels arriveront ici.</p>' : ''}`;
    } catch (er) { if (ok('#etat')) $('#etat').innerHTML = `<p class="alerte err" role="alert">${esc(erreurTexte(er))}</p>`; }
  };
  const comptes = async () => {
    try {
      const r = await get('/api/admin/utilisateurs');
      if (!ok('#comptes')) return;
      $('#comptes').innerHTML = `<div class="defile"><table><tr><th>Identifiant</th><th>Nom</th><th>Rôle</th><th>Zone</th><th>Point</th><th>Dernière connexion</th><th>État</th><th></th></tr>${r.utilisateurs.map((u) =>
        `<tr><td>${esc(u.identifiant)}</td><td>${esc(u.nom)}</td><td>${esc(LIBELLE_ROLE[u.role] || u.role)}</td><td>${esc(u.zone || '-')}</td><td>${esc(u.point || '-')}</td><td>${u.derniere_connexion ? esc(dateFr(u.derniere_connexion)) : 'jamais'}</td><td>${u.actif ? 'actif' : '<b>désactivé</b>'}</td>
        <td>${u.identifiant === moi ? '' : `<button class="secondaire" data-act="${esc(u.identifiant)}" data-etat="${u.actif ? 0 : 1}">${u.actif ? 'Désactiver' : 'Réactiver'}</button> <button class="secondaire" data-mdp="${esc(u.identifiant)}">Nouveau mot de passe</button>`}</td></tr>`).join('')}</table></div>`;
      $$('[data-act]').forEach((b) => (b.onclick = async () => {
        try { await appel('PATCH', '/api/admin/utilisateurs/' + encodeURIComponent(b.dataset.act), { actif: b.dataset.etat === '1' }); toast('Compte mis à jour.'); comptes(); audit(); }
        catch (er) { toast(erreurTexte(er)); }
      }));
      $$('[data-mdp]').forEach((b) => (b.onclick = async () => {
        const mdp = window.prompt(`Nouveau mot de passe pour « ${b.dataset.mdp} » (8 caractères minimum) :`);
        if (!mdp) return;
        try { await appel('PATCH', '/api/admin/utilisateurs/' + encodeURIComponent(b.dataset.mdp), { mot_de_passe: mdp }); toast('Mot de passe modifié ; ses sessions en cours sont fermées.'); audit(); }
        catch (er) { toast(erreurTexte(er)); }
      }));
    } catch (er) { if (ok('#comptes')) $('#comptes').innerHTML = `<p class="alerte err" role="alert">${esc(erreurTexte(er))}</p>`; }
  };
  const audit = async () => {
    try {
      const r = await get('/api/admin/audit?limite=30');
      if (!ok('#audit')) return;
      $('#audit').innerHTML = r.evenements.length
        ? `<div class="defile"><table><tr><th>Date</th><th>Compte</th><th>Action</th><th>Cible</th></tr>${r.evenements.map((x) => `<tr><td>${esc(dateFr(x.date))}</td><td>${esc(x.utilisateur || '-')}</td><td>${esc(x.action)}</td><td>${esc(x.cible || '')}</td></tr>`).join('')}</table></div>`
        : '<p class="mut">Aucun événement.</p>';
    } catch (er) { if (ok('#audit')) $('#audit').innerHTML = `<p class="alerte err" role="alert">${esc(erreurTexte(er))}</p>`; }
  };
  const demo = (id, url, attente, ok_) => {
    $(id).onclick = async (e) => {
      if (id === '#b-retirer' && !window.confirm('Retirer toutes les données SYNTHÉTIQUES (signalements, dépotoirs, interventions de démonstration) ? Les vraies données ne sont pas touchées.')) return;
      e.target.disabled = true; $('#demo-msg').textContent = attente;
      try { const r = await post(url); if (ok('#demo-msg')) $('#demo-msg').textContent = r.message; toast(r.message); etat(); audit(); }
      catch (er) { if (ok('#demo-msg')) $('#demo-msg').textContent = erreurTexte(er); }
      e.target.disabled = false;
    };
  };
  demo('#b-charger', '/api/admin/demo/charger', 'Chargement en cours (quelques dizaines de secondes)…');
  demo('#b-retirer', '/api/admin/demo/retirer', 'Retrait en cours…');
  $('#nouveau').onsubmit = async (e) => {
    e.preventDefault();
    const er = $('#n-err'); er.hidden = true;
    try {
      await post('/api/admin/utilisateurs', { identifiant: $('#n-id').value.trim(), nom: $('#n-nom').value.trim(), role: $('#n-role').value, zone: $('#n-zone').value.trim() || undefined, point: $('#n-point').value.trim() || undefined, mot_de_passe: $('#n-mdp').value });
      toast('Compte créé.'); $('#nouveau').reset(); comptes(); etat(); audit();
    } catch (err) { er.textContent = erreurTexte(err); er.hidden = false; }
  };
  etat(); comptes(); audit();
  return () => { vivant = false; };
}
