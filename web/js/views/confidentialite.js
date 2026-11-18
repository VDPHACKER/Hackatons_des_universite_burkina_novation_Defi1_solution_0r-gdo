export async function render(racine) {
  racine.innerHTML = `<h2>Confidentialité : vos données</h2>
  <div class="alerte info"><b>Un signalement vise un tas d'ordures, jamais une personne.</b> Il n'est jamais une accusation et ne déclenche aucune sanction automatique.</div>
  <h3>Ce qui est collecté quand vous signalez</h3>
  <ul>
    <li><b>La position du tas</b> : le GPS du téléphone (ou la position saisie à la main), avec sa précision.</li>
    <li><b>Jusqu'à 5 photos du tas.</b> Cadrez le tas, pas les personnes. Par sécurité, <b>les visages et les plaques d'immatriculation sont masqués automatiquement sur votre téléphone</b>, avant tout envoi : la photo d'origine ne quitte jamais l'appareil. L'application détecte des visages pour les cacher, jamais pour identifier quelqu'un. Ce masquage est un filet de sécurité, pas une garantie : une personne très éloignée, de dos ou à demi cachée peut passer inaperçue.</li>
    <li><b>Un identifiant d'appareil aléatoire</b>, créé par l'application. Ce n'est pas votre numéro de téléphone. Il sert seulement à repérer l'envoi de dizaines de faux signalements par le même téléphone.</li>
    <li>La date et l'heure, la taille, la nature des déchets, caniveau bouché ou non, accès pour un camion.</li>
  </ul>
  <h3>Ce qui n'est pas demandé</h3>
  <ul><li>Votre nom, votre numéro de téléphone, votre adresse. Les citoyens signalent sans compte.</li><li>Les agents saisissent leur nom pour la revalidation : il figure au journal, car chaque décision doit être traçable.</li></ul>
  <h3>Qui voit quoi</h3>
  <ul><li>Les agents de la commune voient les signalements, leur score et leurs motifs. <b>Les photos ne sont pas conservées</b> : le serveur les analyse (taille, netteté, doublons) puis ne garde qu'une empreinte numérique, qui ne permet pas de reconstituer l'image.</li><li>Le public voit les tas vérifiés sur la carte, sans photo ni identifiant d'appareil.</li><li>L'export vers OpenStreetMap ne contient que la position des tas vérifiés.</li></ul>
  <h3>Conservation et recours</h3>
  <div class="alerte"><b>À confirmer avec la mairie.</b> Proposition de départ : positions des tas vérifiés gardées tant que le tas existe ; messages vocaux effacés après 30 jours ; photos non conservées. Ces durées ne sont pas encore décidées.</div>
  <ul><li>Un signalement n'est jamais effacé de la base (c'est la règle du projet), mais une personne qui s'estime visée peut demander à la mairie de retirer un signalement de la carte publique.</li><li>Si un agent a rejeté à tort un signalement vrai, un autre agent peut le revalider avec un motif.</li></ul>
  <h3>Sur votre téléphone</h3>
  <p>L'application garde sur l'appareil les signalements en attente d'envoi, votre session de connexion (agents et mairie : fermée et effacée à la déconnexion) et vos préférences. Vous pouvez tout effacer en supprimant les données du site dans le navigateur.</p>
  <p><b>Message vocal.</b> Votre voix est une donnée personnelle. Elle n'est écoutée que par la brigade (chaque écoute est inscrite au journal), n'est jamais visible sur la carte publique, et le fichier est <b>effacé automatiquement après 30 jours</b>. Le signalement, lui, est conservé sans votre voix.</p>
  <p><b>« Je le vois aussi » / « Ce tas n'est plus là ».</b> Pour donner cet avis, l'application lit votre position GPS : le serveur vérifie seulement que vous êtes à moins de 150 m du tas, puis ne la garde pas (seule la distance mesurée est conservée). L'avis est lié à un identifiant d'appareil aléatoire, jamais à votre nom.</p>
  <p class="petit mut">Texte informatif, non un avis juridique.</p>`;
}
