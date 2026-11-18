// Lecture minimale EXIF (date de prise de vue + GPS) avant compression, qui supprime les EXIF.
export async function lireExif(file) {
  try {
    const b = new DataView(await file.slice(0, 131072).arrayBuffer());
    if (b.getUint16(0) !== 0xffd8) return null;
    let o = 2;
    while (o < b.byteLength - 4) {
      const m = b.getUint16(o), l = b.getUint16(o + 2);
      if (m === 0xffe1 && b.getUint32(o + 4) === 0x45786966) return tiff(b, o + 10);
      if ((m & 0xff00) !== 0xff00) break;
      o += 2 + l;
    }
  } catch (e) {}
  return null;
}
function tiff(b, t) {
  const le = b.getUint16(t) === 0x4949;
  const u16 = (p) => b.getUint16(p, le), u32 = (p) => b.getUint32(p, le);
  const out = {};
  const str = (p, n) => { let s = ''; for (let i = 0; i < n - 1; i++) s += String.fromCharCode(b.getUint8(p + i)); return s; };
  const rat = (p) => u32(p) / (u32(p + 4) || 1);
  const ifd = (p, f) => { const n = u16(p); for (let i = 0; i < n; i++) f(p + 2 + i * 12); };
  let exifP = 0, gpsP = 0;
  ifd(t + u32(t + 4), (e) => { const tag = u16(e); if (tag === 0x8769) exifP = u32(e + 8); if (tag === 0x8825) gpsP = u32(e + 8); });
  if (exifP) ifd(t + exifP, (e) => { if (u16(e) === 0x9003) { const n = u32(e + 4); out.date = str(t + u32(e + 8), n).replace(/^(\d{4}):(\d\d):(\d\d) /, '$1-$2-$3T'); } });
  if (gpsP) {
    const g = {};
    ifd(t + gpsP, (e) => { const tag = u16(e); if (tag === 1 || tag === 3) g[tag] = String.fromCharCode(b.getUint8(e + 8)); if (tag === 2 || tag === 4) { const p = t + u32(e + 8); g[tag] = rat(p) + rat(p + 8) / 60 + rat(p + 16) / 3600; } });
    if (g[2] != null && g[4] != null) { out.lat = g[2] * (g[1] === 'S' ? -1 : 1); out.lon = g[4] * (g[3] === 'W' ? -1 : 1); }
  }
  return Object.keys(out).length ? out : null;
}
export async function compresser(file, eco) {
  const max = eco ? 640 : 1024, q = eco ? 0.5 : 0.7;
  const bmp = await createImageBitmap(file);
  const k = Math.min(1, max / Math.max(bmp.width, bmp.height));
  const c = document.createElement('canvas'); c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
  c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
  return new Promise((res) => c.toBlob(res, 'image/jpeg', q));
}
