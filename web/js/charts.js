// Graphiques SVG maison (aucune bibliothèque) : courbes, accessibles (titre + tableau repliable).
import { esc, nf } from './util.js';
export const COULEURS = ['#0b5c3a', '#c4202a', '#0057c8', '#c46a00'];
export function courbes({ titre, x, series, unite = '', hauteur = 200 }) {
  const W = 520, H = hauteur, m = { l: 46, r: 10, t: 12, b: 26 };
  const toutes = series.flatMap((s) => s.data).filter((v) => v != null && !isNaN(v));
  if (!toutes.length) return '<p class="mut">Pas de données.</p>';
  const mx = Math.max(...toutes, 1e-9) * 1.05, mn = Math.min(0, ...toutes), n = Math.max(...series.map((s) => s.data.length)) - 1 || 1;
  const px = (i) => m.l + (i / n) * (W - m.l - m.r), py = (v) => H - m.b - ((v - mn) / (mx - mn)) * (H - m.t - m.b);
  const grille = [0, 0.5, 1].map((f) => { const v = mn + (mx - mn) * f; return `<line x1="${m.l}" x2="${W - m.r}" y1="${py(v)}" y2="${py(v)}" stroke="#8884" /><text x="${m.l - 4}" y="${py(v) + 4}" text-anchor="end">${nf(v, v < 10 ? 1 : 0)}</text>`; }).join('');
  const xs = [0, 0.5, 1].map((f) => `<text x="${px(f * n)}" y="${H - 8}" text-anchor="middle">${x ? nf(x[Math.round(f * n)] ?? Math.round(f * n)) : Math.round(f * n)}</text>`).join('');
  const lignes = series.map((s, k) => `<polyline fill="none" stroke="${s.couleur || COULEURS[k]}" stroke-width="3" ${s.pointille ? 'stroke-dasharray="7 5"' : ''} points="${s.data.map((v, i) => `${px(i).toFixed(1)},${py(v).toFixed(1)}`).join(' ')}"/>`).join('');
  const leg = series.map((s, k) => `<span style="color:${s.couleur || COULEURS[k]};font-weight:700">${s.pointille ? '┅' : '━'} ${esc(s.nom)}</span>`).join(' &nbsp; ');
  const tab = `<details><summary>Voir les valeurs</summary><div class="defile"><table><tr><th>Jour</th>${series.map((s) => `<th>${esc(s.nom)}</th>`).join('')}</tr>${[0, .25, .5, .75, 1].map((f) => { const i = Math.round(f * n); return `<tr><td>${x ? x[i] : i}</td>${series.map((s) => `<td>${nf(s.data[i], 1)} ${esc(unite)}</td>`).join('')}</tr>`; }).join('')}</table></div></details>`;
  return `<figure style="margin:8px 0"><figcaption><b>${esc(titre)}</b> <span class="mut petit">${esc(unite)}</span><br>${leg}</figcaption><svg class="graph" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(titre)}">${grille}${xs}${lignes}</svg>${tab}</figure>`;
}
export function barres(titre, items) {
  const mx = Math.max(...items.map((i) => i.v), 1e-9);
  return `<figure style="margin:8px 0"><figcaption><b>${esc(titre)}</b></figcaption>${items.map((i) => `<div style="display:flex;align-items:center;gap:8px;margin:4px 0"><span style="width:38%;font-size:.85rem">${esc(i.nom)}</span><div style="flex:1;background:var(--carte);border:1px solid var(--bord)"><div style="width:${(i.v / mx) * 100}%;background:${i.couleur || '#0b5c3a'};height:18px"></div></div><b style="min-width:70px;text-align:right">${nf(i.v, 1)}</b></div>`).join('')}</figure>`;
}
