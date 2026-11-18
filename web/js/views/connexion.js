import { $, toast, erreurTexte } from '../util.js';
import { post } from '../api.js';
import { ECRANS } from '../acces.js';
import { ouvrir, connecte, role } from '../session.js';

// Premier écran de chaque rôle après la connexion.
const ARRIVEE = { precollecteur: 'precollecteur', brigade: 'verifier', mairie: 'mairie', admin: 'admin' };

export async function render(racine, params) {
  if (connecte()) { location.replace('#/' + (ARRIVEE[role()] || 'accueil')); return; }
  racine.innerHTML = `<h2>Connexion</h2>
  <p class="mut">Pour les pré-collecteurs, les agents de la brigade Laabal, la mairie et l'administration. Les habitants n'ont pas besoin de compte : ils signalent et suivent un tas depuis l'accueil.</p>
  <form id="f" class="carte form-connexion" novalidate>
    <label for="identifiant">Identifiant</label>
    <input id="identifiant" name="username" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" inputmode="email" required>
    <label for="mdp">Mot de passe</label>
    <div class="champ-mdp"><input id="mdp" name="password" type="password" autocomplete="current-password" autocapitalize="none" autocorrect="off" spellcheck="false" required>
      <button type="button" id="voir-mdp" class="secondaire" aria-pressed="false" aria-controls="mdp">Afficher</button></div>
    <p id="erreur" class="alerte err" role="alert" hidden></p>
    <button class="primaire" type="submit" id="b-co">Se connecter</button>
  </form>
  <p class="petit mut">Mot de passe oublié ou compte bloqué (5 échecs = 15 minutes) : l'administrateur le réinitialise depuis l'écran Administration, ou sur le serveur avec <code>scripts\\comptes.bat</code>.</p>`;
  $('#voir-mdp').onclick = (e) => {
    const champ = $('#mdp'), visible = champ.type === 'password';
    champ.type = visible ? 'text' : 'password'; e.currentTarget.textContent = visible ? 'Masquer' : 'Afficher';
    e.currentTarget.setAttribute('aria-pressed', String(visible)); champ.focus();
  };
  $('#f').onsubmit = async (e) => {
    e.preventDefault();
    const er = $('#erreur'); er.hidden = true;
    const identifiant = $('#identifiant').value.trim(), mot_de_passe = $('#mdp').value;
    if (!identifiant || !mot_de_passe) { er.textContent = 'Saisissez votre identifiant et votre mot de passe.'; er.hidden = false; return; }
    $('#b-co').disabled = true;
    try {
      const r = await post('/api/auth/connexion', { identifiant, mot_de_passe });
      const retour = params.get('retour');
      ouvrir(r);
      toast(`Bienvenue ${r.utilisateur.nom}.`);
      location.hash = '#/' + (retour && ECRANS[retour] ? retour : ARRIVEE[r.utilisateur.role] || 'accueil');
    } catch (err) {
      er.textContent = err.status === 401 ? 'Identifiant ou mot de passe incorrect.' : erreurTexte(err);
      er.hidden = false; $('#mdp').value = ''; $('#mdp').focus();
    }
    const bouton = $('#b-co');           // absent si la connexion a réussi : l'écran a déjà été remplacé
    if (bouton) bouton.disabled = false;
  };
  $('#identifiant').focus();
}
