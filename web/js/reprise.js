// Reprise des réglages gardés par une version précédente de l'application (ancien nom technique « laabal ») :
// session, langue, thème, identifiant de l'appareil… Importé EN PREMIER par app.js, avant tout module qui lit ces réglages.
try {
  for (let i = localStorage.length - 1; i >= 0; i--) {
    const k = localStorage.key(i);
    if (k && k.startsWith('laabal.')) {
      const n = 'oregdo.' + k.slice('laabal.'.length);
      if (localStorage.getItem(n) === null) localStorage.setItem(n, localStorage.getItem(k));
      localStorage.removeItem(k);
    }
  }
} catch (e) { /* stockage indisponible (navigation privée) : rien à reprendre */ }
