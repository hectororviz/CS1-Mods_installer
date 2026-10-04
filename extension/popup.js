/* CS1 Mods Installer · popup de la extensión (Manifest V3).
 * Puerta de entrada al gestor local: abre el sitio, muestra cuántos mods hay
 * instalados/indexados y permite ampliar el índice sin abrir la web.
 */
'use strict';

const PORTS = [8787, 8788, 8789, 8790, 8791, 8792, 8793, 8794, 8795, 8796];
const STORE_KEY = 'cs1base';

let base = null;

const $ = (id) => document.getElementById(id);

async function probe(url, ms = 1200) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), ms);
  try {
    const r = await fetch(url, { signal: ctl.signal });
    return r.ok ? r : null;
  } catch {
    return null;
  } finally {
    clearTimeout(t);
  }
}

async function findBackend() {
  if (base && await probe(base + '/health')) return true;
  base = null;
  try {
    const saved = await chrome.storage.local.get(STORE_KEY);
    if (saved[STORE_KEY] && await probe(saved[STORE_KEY] + '/health')) {
      base = saved[STORE_KEY];
      return true;
    }
  } catch { /* sin storage: se prueban puertos */ }
  const found = (await Promise.all(
    PORTS.map(async (p) => (await probe(`http://127.0.0.1:${p}/health`)) ? `http://127.0.0.1:${p}` : null)
  )).find(Boolean) || null;
  base = found;
  if (found) {
    try { await chrome.storage.local.set({ [STORE_KEY]: found }); } catch { /* da igual */ }
  }
  return !!found;
}

async function refresh() {
  const ok = await findBackend();
  if (!ok) {
    $('status').textContent = 'Backend apagado: abre CS1 Mods Installer.';
    $('open').disabled = true;
    $('idx').disabled = true;
    return;
  }
  $('open').disabled = false;
  $('idx').disabled = false;
  try {
    const st = await (await fetch(base + '/api/state')).json();
    const n = (v) => Number(v || 0).toLocaleString('es');
    $('status').textContent =
      `${n(st.counts?.installed)} instalados · ${n(st.index?.entries)} en índice`;
  } catch {
    $('status').textContent = 'Backend en ' + base;
  }
}

$('open').addEventListener('click', async () => {
  if (!await findBackend()) return refresh();
  chrome.tabs.create({ url: base + '/' });
  window.close();
});

$('idx').addEventListener('click', async () => {
  if (!await findBackend()) return refresh();
  $('idx').disabled = true;
  $('msg').textContent = 'Ampliando índice…';
  try {
    const { job } = await (await fetch(base + '/api/index', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pages: 100 }),
    })).json();
    const tick = async () => {
      const j = await (await fetch(`${base}/api/job/${job.id}`)).json();
      $('msg').textContent = j.step || j.state;
      if (j.state === 'done' || j.state === 'error') {
        $('idx').disabled = false;
        refresh();
        return;
      }
      setTimeout(tick, 1500);
    };
    tick();
  } catch (e) {
    $('msg').textContent = 'No se pudo iniciar: ' + (e.message || e);
    $('idx').disabled = false;
  }
});

refresh();
