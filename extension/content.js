/* CS1 Mods Installer · content script para smods.ru (Manifest V3).
 * Pone un botón flotante en cada ficha (smods.ru/archives/…) que manda la
 * URL al backend local (127.0.0.1) y muestra el progreso de instalación.
 * Sin frameworks, sin librerías: fetch + DOM.
 */
'use strict';

const PORTS = [8787, 8788, 8789, 8790, 8791, 8792, 8793, 8794, 8795, 8796];
const STORE_KEY = 'cs1base';

let base = null;
let busy = false;

function pageUrl() {
  const canon = document.querySelector('link[rel="canonical"]');
  const u = (canon && canon.href) || location.href;
  const m = u.match(/smods\.ru\/archives\/(\d+)/);
  return m ? `https://smods.ru/archives/${m[1]}` : null;
}

async function get(path, timeoutMs = 1500) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const r = await fetch(base + path, { signal: ctl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  } finally {
    clearTimeout(t);
  }
}

async function findBackend() {
  if (base) {
    try { await get('/health', 1200); return true; }
    catch { base = null; }
  }
  try {
    const saved = await chrome.storage.local.get(STORE_KEY);
    if (saved[STORE_KEY]) {
      base = saved[STORE_KEY];
      try { await get('/health', 1200); return true; }
      catch { base = null; }
    }
  } catch { /* storage no disponible: se sigue probando puertos */ }
  const probes = PORTS.map((p) => (async () => {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 1200);
    try {
      const r = await fetch(`http://127.0.0.1:${p}/health`, { signal: ctl.signal });
      if (r.ok) return `http://127.0.0.1:${p}`;
    } catch { /* siguiente */ } finally {
      clearTimeout(t);
    }
    return null;
  })());
  const found = (await Promise.all(probes)).find(Boolean) || null;
  base = found;
  if (found) {
    try { await chrome.storage.local.set({ [STORE_KEY]: found }); } catch { /* da igual */ }
  }
  return !!found;
}

function paint(btn, label, mode) {
  btn.textContent = label;
  btn.dataset.mode = mode || '';
}

async function poll(btn, jobId) {
  const tick = async () => {
    let j;
    try {
      j = await get(`/api/job/${jobId}`, 4000);
    } catch {
      paint(btn, '⏳ reintentando…', 'busy');
      setTimeout(tick, 2000);
      return;
    }
    if (j.state === 'done') {
      const where = (((j.detail || {}).installed || {}).path || '').split('/').slice(-3).join('/');
      paint(btn, '✔ Instalado' + (where ? ` (${where})` : ''), 'done');
      busy = false;
      return;
    }
    if (j.state === 'error') {
      paint(btn, '✖ Falló', 'error');
      btn.title = j.error || 'Error desconocido';
      busy = false;
      return;
    }
    const pct = Math.round((j.progress || 0) * 100);
    paint(btn, `⏳ ${j.step || 'trabajando…'} ${pct}%`, 'busy');
    setTimeout(tick, 1000);
  };
  tick();
}

async function install(btn) {
  if (busy) return;
  const url = pageUrl();
  if (!url) {
    paint(btn, '✖ No es una ficha', 'error');
    return;
  }
  busy = true;
  paint(btn, '🔎 Buscando backend…', 'busy');
  if (!(await findBackend())) {
    paint(btn, '⚠ Abre CS1 Mods Installer primero', 'error');
    btn.title = 'El backend local no responde en 127.0.0.1:8787-8796. Ábrelo desde el menú y reintenta.';
    busy = false;
    return;
  }
  paint(btn, '⬇ Enviando…', 'busy');
  try {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 15000);
    let r;
    try {
      r = await fetch(base + '/api/install', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
        signal: ctl.signal,
      });
    } finally {
      clearTimeout(t);
    }
    if (!r.ok) {
      let msg = `HTTP ${r.status}`;
      try { msg = (await r.json()).detail || msg; } catch { /* texto */ }
      throw new Error(msg);
    }
    const d = await r.json();
    poll(btn, d.job.id);
  } catch (e) {
    paint(btn, '✖ Error al enviar', 'error');
    btn.title = String((e && e.message) || e);
    busy = false;
  }
}

function mount() {
  if (!/\/archives\/\d+/.test(location.pathname)) return;
  if (document.getElementById('cs1-install-btn')) return;
  const css = document.createElement('style');
  css.textContent = `
    #cs1-install-btn {
      position: fixed; right: 18px; bottom: 18px; z-index: 2147483647;
      padding: 12px 18px; border: 0; border-radius: 10px; cursor: pointer;
      font: 600 14px/1.2 system-ui, sans-serif; color: #fff; background: #1f7a4d;
      box-shadow: 0 4px 18px rgba(0,0,0,.45);
    }
    #cs1-install-btn:hover { background: #249058; }
    #cs1-install-btn[data-mode="busy"] { background: #6b5d2a; cursor: wait; }
    #cs1-install-btn[data-mode="done"] { background: #1f7a4d; }
    #cs1-install-btn[data-mode="error"] { background: #8c2f2f; }
  `;
  document.documentElement.appendChild(css);
  const btn = document.createElement('button');
  btn.id = 'cs1-install-btn';
  btn.type = 'button';
  paint(btn, '⬇ Instalar en CS1', '');
  btn.title = 'Instalar este mod con CS1 Mods Installer (backend local)';
  btn.addEventListener('click', () => install(btn));
  document.documentElement.appendChild(btn);
}

mount();
