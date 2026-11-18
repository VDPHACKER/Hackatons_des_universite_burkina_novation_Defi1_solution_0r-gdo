import { esc, ecouter } from '../util.js';
import { icone } from '../icones.js';

export async function render(racine) {
  const d = await fetch('data/droits.json').then((r) => r.json());
  const ic = { A: '●●●', B: '●●○', C: '●○○', NV: '○○○' };
  const cert = (c) => `<span class="badge c-${c}" title="${esc(d.certitudes[c])}">${esc(d.certitudes[c])} ${ic[c]}</span>`;
  const sec = (s) => `<h3>${esc(s.titre)}</h3>${s.items.map((i) => `<details class="cert" id="${esc(i.id)}"><summary>${esc(i.titre)}</summary>
    <p>${esc(i.texte)}</p><p><b>Base :</b> ${esc(i.base)}<br><b>Sanction :</b> ${esc(i.sanction)}</p>${i.note ? `<p class="petit mut">${esc(i.note)}</p>` : ''}<p>${cert(i.certitude)}</p></details>`).join('')}`;
  const [faire, interdit, controle, droits] = d.sections;
  racine.innerHTML = `<h2>Droits et devoirs des ménages</h2>
  <div class="alerte info"><b>Informatif, non un avis juridique.</b> ${esc(d.avertissement)}</div>
  <p><button class="secondaire" id="b-ecouter">${icone('volume', 18)} Écouter le résumé</button> <span class="petit mut">Lecture à voix haute en français seulement ; l'interface existe en dioula et mooré (brouillons).</span></p>
  <div class="carte"><h3 style="margin-top:0">${esc(d.conseils.titre)}</h3><ul>${d.conseils.items.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div>
  <p>Le but de ces règles est que la ville reste propre et en bonne santé. <b>D'abord on explique et on aide, on sanctionne en dernier recours.</b></p>
  ${sec(faire)}${sec(droits)}${sec(interdit)}
  <h3>Et si une règle n'est pas respectée ?</h3>
  <div class="carte"><b>1. ${esc(d.phases[0].nom)}</b><p>${esc(d.phases[0].texte)}</p>${cert(d.phases[0].certitude)}</div>
  <details class="cert"><summary>2. ${esc(d.phases[1].nom)}</summary><p>${esc(d.phases[1].texte)}</p>${cert(d.phases[1].certitude)}</details>
  ${sec(controle)}
  <details class="cert"><summary>Que veulent dire les niveaux de confiance ?</summary><ul>${Object.entries(d.certitudes).map(([k, v]) => `<li><b class="c-${k}">${esc(v)}</b> ${ic[k]}</li>`).join('')}</ul></details>
  <p class="petit mut">Signaler à la brigade Laabal : 50 40 05 04. Les règles peuvent évoluer : vérifiez auprès de la mairie. <a href="#/confidentialite">Vos données</a></p>`;
  const resume = "Droits et devoirs des ménages. Informatif, ce n'est pas un avis juridique. " + d.conseils.titre + '. ' + d.conseils.items.join(' ') + " D'abord, on explique et on aide. On sanctionne seulement en cas de refus ou de récidive.";
  document.getElementById('b-ecouter').onclick = () => ecouter(resume);
}
