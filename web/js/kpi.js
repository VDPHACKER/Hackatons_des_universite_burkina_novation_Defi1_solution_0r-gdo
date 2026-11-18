import { nf } from './util.js';
// sens : +1 = une hausse est « mieux », -1 = une hausse est « moins bien », 0 = à lire avec la couverture.
const DEFS = [
  ['couverture', 'Ménages desservis', '%', 0, +1, 'Part des ménages qui ont un point de regroupement à portée.'],
  ['tonnes', 'Déchets évacués', 't par jour', 0, +1, 'Tonnes réellement ramassées chaque jour.'],
  ['fuite', 'Fuite vers les dépotoirs', '%', 1, -1, 'Part des déchets qui finissent dans des dépotoirs faute de collecte.'],
  ['valorise', 'Déchets triés et revendus', 't par jour', 1, +1, 'Recyclables (plastiques, métaux, papier) qui ne passent pas par la collecte. Hypothèses à confirmer avec les filières locales.'],
  ['recette_valo', 'Recettes de la revente', 'FCFA par jour', 0, +1, 'Partagées entre les ménages et les pré-collecteurs. Prix de rachat : hypothèse.'],
  ['distance_km', 'Distance des tournées', 'km par jour', 1, 0, 'Une distance plus courte n\'est un progrès que si on ramasse autant.'],
  ['cout_fcfa', 'Coût de collecte', 'FCFA par jour', 0, 0, 'Un coût plus bas n\'est un progrès que si on ramasse autant.'],
];
export const KPI_DEFS = DEFS.map(([c, t, u, d]) => [c, t, u, d]);
const rel = (a, b) => (b ? (a - b) / Math.abs(b) : 0);

// Verdict global : couverture et tonnes évacuées décident ; la fuite complète.
export function verdictGlobal(k, avant) {
  if (!avant) return null;
  let pts = 0, txt = [];
  for (const c of ['couverture', 'tonnes']) if (k[c] != null && avant[c] != null) { const r = rel(k[c], avant[c]); if (Math.abs(r) > 0.01) { pts += r > 0 ? 1 : -1; } }
  if (k.fuite != null && avant.fuite != null && Math.abs(k.fuite - avant.fuite) > 0.5) pts += k.fuite < avant.fuite ? 1 : -1;
  if (k.couverture != null && avant.couverture != null && Math.abs(k.couverture - avant.couverture) >= 0.5) txt.push(`couverture ${k.couverture > avant.couverture ? '+' : ''}${nf(k.couverture - avant.couverture, 1)} point(s)`);
  if (k.tonnes != null && avant.tonnes != null && Math.abs(k.tonnes - avant.tonnes) >= 0.5) txt.push(`${k.tonnes > avant.tonnes ? '+' : ''}${nf(k.tonnes - avant.tonnes)} t évacuées par jour`);
  const m = pts > 0 ? ['delta-b', '▲ Au total : mieux'] : pts < 0 ? ['delta-m', '▼ Au total : moins bien'] : ['mut', '＝ Au total : pas de changement net'];
  return `<p class="${m[0]}" style="font-size:1.05rem">${m[1]}${txt.length ? ' (' + txt.join(', ') + ')' : ''}</p>`;
}
export function kpiHtml(k, avant) {
  const perte = avant && ['couverture', 'tonnes'].some((c) => k[c] != null && avant[c] != null && rel(k[c], avant[c]) < -0.01);
  return (avant ? verdictGlobal(k, avant) : '') + '<div class="grille">' + DEFS.map(([c, t, u, d, sens, aide]) => {
    if (k[c] == null) return '';
    let delta = '';
    if (avant && avant[c] != null && Math.abs(k[c] - avant[c]) >= 0.5 * Math.pow(10, -d)) {
      const diff = k[c] - avant[c]; const fl = diff > 0 ? '▲ +' : '▼ ';
      // Distance et coût : jamais « mieux » quand on ramasse moins.
      const s = sens === 0 ? (perte ? 0 : -1) : sens;
      const cl = s === 0 ? 'mut' : diff * s > 0 ? 'delta-b' : 'delta-m';
      const mot = s === 0 ? '(à lire avec la couverture)' : diff * s > 0 ? '(mieux)' : '(moins bien)';
      delta = `<br><span class="${cl}">${fl}${nf(diff, d)} ${mot}</span>`;
    }
    return `<div class="kpi" title="${aide}"><span>${t}</span><b>${nf(k[c], d)} <small>${u}</small></b>${delta}<small class="mut">${aide}</small></div>`;
  }).join('') + '</div>';
}
// Diagnostic du stock de dépotoirs : celui du moteur (B) si présent, sinon calculé sur la série.
export function diagnosticHtml(diag, serie) {
  let tendance = diag?.tendance, message = diag?.message;
  const stock = serie?.depotoirs_tonnes;
  if (!message && stock && stock.length > 10) {
    const a = stock[Math.floor(stock.length / 2)], z = stock[stock.length - 1];
    tendance = z > a * 1.03 ? 'croissant' : z < a * 0.97 ? 'decroissant' : 'stable';
    message = tendance === 'croissant' ? `Le stock de dépotoirs augmente (${nf(a)} t puis ${nf(z)} t) : le plan ne suffit pas à enrayer les dépôts sauvages.` : tendance === 'decroissant' ? `Le stock de dépotoirs diminue (${nf(a)} t puis ${nf(z)} t).` : 'Le stock de dépotoirs est stable.';
  }
  if (!message) return '';
  const rouge = /crois|haus|aggrav/i.test(tendance || '') || /ne suffit pas/i.test(message);
  return `<div class="alerte ${rouge ? 'err' : 'info'}" role="status"><b>${rouge ? '▲ Stock en hausse. ' : 'Stock de dépotoirs. '}</b>${message.replace(/&/g, '&amp;').replace(/</g, '&lt;')}</div>`;
}
