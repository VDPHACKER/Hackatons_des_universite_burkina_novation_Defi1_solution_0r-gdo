// Vérification de bout en bout de la PWA (mode mock). Reprend les parcours exécutés à la main via Playwright MCP.
// Pré-requis : `npm i playwright` (hors dépôt) + `npx playwright install chromium`, puis, depuis web/ :
//   ..\.venv\Scripts\python.exe -m http.server 8080      (autre terminal)
//   node tests/e2e/parcours.mjs [http://localhost:8080]
import { chromium } from 'playwright';
import assert from 'node:assert/strict';

const BASE = process.argv[2] || 'http://localhost:8080';
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 390, height: 844 } });
const page = await ctx.newPage();
const erreurs = [];
page.on('pageerror', (e) => erreurs.push(e.message));

// 1. Les 8 écrans s'affichent, sans débordement horizontal
await page.goto(`${BASE}/index.html?mock=1#/accueil`);
await page.evaluate(() => localStorage.setItem('oregdo.jeton', 'jury-demo')); // jeton de démonstration
assert.match(await page.locator('#vue').innerText(), /30 secondes/);
for (const v of ['accueil', 'confidentialite', 'carte', 'signaler', 'verifier', 'plan', 'scenarios', 'jury', 'droits', 'commun']) {
  await page.goto(`${BASE}/index.html#/${v}`); await page.waitForTimeout(1500);
  const w = await page.evaluate(() => document.body.scrollWidth - innerWidth);
  assert.ok(w <= 0, `débordement horizontal sur ${v}`);
}
// 2. Signalement hors ligne puis synchronisation
await page.goto(`${BASE}/index.html#/signaler`); await page.reload(); await page.waitForTimeout(1500);
await ctx.setOffline(true); await page.evaluate(() => window.dispatchEvent(new Event('offline')));
await page.click('summary:has-text("Saisir la position")');
await page.fill('#lat', '12.37'); await page.fill('#lon', '-1.52');
await page.check('#sans-photo'); await page.check('input[name=taille][value=moyen]'); await page.click('#envoyer');
await page.waitForTimeout(600);
assert.match(await page.locator('#file').innerText(), /en attente/);
await ctx.setOffline(false); await page.evaluate(() => window.dispatchEvent(new Event('online')));
await page.waitForTimeout(2500);
assert.match(await page.locator('#mes').innerText(), /pts/);
// 2b. Erreur technique 422 : le signalement reste en file (jamais « Rejeté »)
await page.goto(`${BASE}/index.html#/signaler`); await page.waitForTimeout(800);
await page.route('**/api/signalements', (r) => r.request().method() === 'POST' ? r.fulfill({ status: 422, contentType: 'application/json', body: '{"detail":[{"loc":["body","nature"],"msg":"x"}]}' }) : r.continue());
await page.evaluate(() => { document.querySelector('#f details').open = true; });
await page.fill('#lat', '12.38'); await page.fill('#lon', '-1.50'); await page.check('#sans-photo'); await page.check('input[name=taille][value=petit]'); await page.click('#envoyer');
await page.waitForTimeout(1200);
assert.match(await page.locator('#mes').innerText(), /En attente d'envoi/);
assert.ok(!(await page.locator('#vue').innerText()).includes('Rejeté'));
await page.unrouteAll();
// 3. Jury : panne de camion, recalcul < 5 s affiché
await page.goto(`${BASE}/index.html#/jury`); await page.waitForTimeout(2000);
await page.click('#a-panne'); await page.waitForTimeout(1500);
assert.match(await page.locator('#resume').innerText(), /sous 5 s/);
await page.click('#a-piege'); await page.waitForTimeout(2000);
assert.match(await page.locator('#resume').innerText(), /0 vérifiés/);
// 4. Vérification : revalidation avec agent et motif, inscrite au journal
await page.goto(`${BASE}/index.html#/verifier`); await page.waitForTimeout(1500);
await page.locator('[data-ouvrir]').first().click();
await page.locator('[id^=ag-]').first().fill('Agent Test'); await page.locator('[id^=mo-]').first().fill('Vérifié sur place');
await page.locator('[data-d=verifie]').first().click(); await page.waitForTimeout(1200);
assert.match(await page.locator('#journal').innerText(), /Agent Test/);
// 5. Hors ligne : l'application se recharge depuis le service worker
await page.goto(`${BASE}/index.html#/droits`); await page.waitForTimeout(2500);
await ctx.setOffline(true); await page.reload(); await page.waitForTimeout(2000);
assert.match(await page.locator('#vue').innerText(), /Droits et devoirs/);
await ctx.setOffline(false);

assert.deepEqual(erreurs, [], 'erreurs JS : ' + erreurs.join(' | '));
console.log('OK : tous les contrôles passent');
await b.close();
