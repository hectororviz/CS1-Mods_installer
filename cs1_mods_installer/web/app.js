/* CS1 Mods Installer · cliente web. Sin frameworks: fetch + DOM, y ya. */
'use strict';

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const S = {
  view: 'browse',
  page: 1,
  kind: '',
  hideInstalled: false,
  onlyCompat: false,
  iFilter: '',
  cards: [],
  installed: [],
  game: null,
  polling: null,
};

/* ── utilidades ──────────────────────────────────────────────── */

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function humanSize(n) {
  if (!n) return '—';
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0, v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return (i === 0 ? v : v.toFixed(1)) + ' ' + u[i];
}

async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try { const j = await r.json(); msg = j.detail || msg; } catch { /* no json */ }
    throw new Error(msg);
  }
  return r.json();
}

function toast(title, sub = '', kind = '') {
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.innerHTML = `<div class="t">${esc(title)}</div>${sub ? `<div class="s">${esc(sub)}</div>` : ''}`;
  $('#toasts').append(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); },
    kind === 'err' ? 9000 : 4800);
}

function banner(msg, kind = '') {
  const b = $('#banner');
  if (!msg) { b.hidden = true; return; }
  b.className = 'banner ' + kind;
  b.innerHTML = msg;
  b.hidden = false;
}

/* ── etiquetas de una tarjeta ────────────────────────────────── */

function badges(c) {
  const out = [];
  if (!c.url && c.steam_url) out.push(`<span class="tag steam">solo en Steam</span>`);
  if (c.compat_status === 'ok') out.push(`<span class="tag ok">✔ ${esc(c.compat)}</span>`);
  else if (c.compat_status === 'mismatch') out.push(`<span class="tag warn">⚠ es para ${esc(c.compat)}</span>`);
  if (c.installed) out.push(`<span class="tag installed">${c.enabled ? 'instalado' : 'desactivado'}</span>`);
  if (c.managed) out.push(`<span class="tag info">gestionado</span>`);
  if (c.workshop_id) out.push(`<span class="tag">ID ${esc(c.workshop_id)}</span>`);
  return out.join('');
}

/* ── catálogo ────────────────────────────────────────────────── */

function visible(c) {
  if (S.kind && c.kind !== S.kind) return false;
  if (S.hideInstalled && c.installed) return false;
  if (S.onlyCompat && S.game && c.compat && c.compat !== S.game.version) return false;
  return true;
}

function renderGrid() {
  const grid = $('#grid');
  const list = S.cards.filter(visible);
  if (!list.length) {
    grid.innerHTML = `<div class="empty">No hay mods que mostrar con estos filtros.</div>`;
    return;
  }
  grid.innerHTML = list.map((c, i) => {
    const img = c.preview_url && c.workshop_id
      ? `<img loading="lazy" src="/api/image/${c.workshop_id}" alt="${esc(c.title)}"
            onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'noimg',textContent:'📦'}))">`
      : `<div class="thumb-placeholder skeleton"></div>`;
    const kindBadge = c.kind && c.kind !== 'unknown'
      ? `<span class="kind ${esc(c.kind)}">${esc(c.kind)}</span>`
      : '';
    const badgesHtml = badges(c);
    const steamOnly = !c.url && c.steam_url;
    return `
    <article class="card${steamOnly ? ' steam-only' : ''}" data-url="${esc(c.url)}" data-steam="${esc(c.steam_url || '')}" data-i="${i}">
      <div class="thumb">
        ${img}
        ${kindBadge}
      </div>
      <div class="body">
        <div class="name">${esc(c.title)}</div>
        <div class="facts">
          <span>${humanSize(c.size || 0)}</span>
          ${c.author ? `<span>· ${esc(c.author)}</span>` : ''}
        </div>
        <div class="tags">${badgesHtml}</div>
      </div>
    </article>`;
  }).join('');

  $$('.card', grid).forEach((el) =>
    el.addEventListener('click', () => {
      if (el.dataset.url) { openModal(el.dataset.url); return; }
      if (el.dataset.steam) {
        window.open(el.dataset.steam, '_blank', 'noopener');
        banner('Ese mod aún no está en tu índice local: amplía el índice (pestaña Índice) para poder instalarlo desde aquí.', '');
      }
    }));
}

async function loadBrowse(page = 1) {
  S.page = page;
  $('#pageInfo').textContent = `página ${page}`;
  $('#grid').innerHTML = Array.from({ length: 10 }, () =>
    '<div class="skeleton" style="aspect-ratio:3/4"></div>').join('');
  try {
    const d = await api(`/api/browse?page=${page}`);
    S.cards = d.cards;
    renderGrid();
    await enrichPartial();
  } catch (e) {
    $('#grid').innerHTML = `<div class="empty">No se pudo cargar el catálogo.<br><small>${esc(e.message)}</small></div>`;
    banner(`Error leyendo smods.ru: ${esc(e.message)}`, 'err');
  }
}

async function doSearch(q) {
  $('#qClear').hidden = !q;
  $('#qSteam').hidden = !q;
  try {
    const d = await api(`/api/search?q=${encodeURIComponent(q)}`);
    S.cards = d.cards;
    S.page = 1;
    $('#pageInfo').textContent = `${d.cards.length} resultado(s) de ${d.searched} indexados`;
    $('#prev').disabled = $('#next').disabled = true;
    renderGrid();
    await enrichPartial();
    if (d.cards.length === 0) {
      banner(`Sin resultados en tu índice local. Pulsa <b>Steam 🌐</b> para buscar online.`, '');
    } else {
      banner(`Búsqueda local sobre ${d.searched} mods indexados. ¿No está? Pulsa <b>Steam 🌐</b>.`, '');
    }
  } catch (e) {
    $('#grid').innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    if (e.message.includes('índice')) banner(
      `${esc(e.message)} <button id="goIdx">Ir al índice</button>`, 'err');
    $('#goIdx')?.addEventListener('click', () => switchView('index'));
  }
}

async function doSearchOnline(q) {
  $('#qClear').hidden = !q;
  $('#qSteam').hidden = !q;
  $('#grid').innerHTML = Array.from({ length: 6 }, () =>
    '<div class="skeleton" style="aspect-ratio:3/4"></div>').join('');
  try {
    const d = await api(`/api/search_online?q=${encodeURIComponent(q)}&limit=30`);
    S.cards = d.cards;
    S.page = 1;
    const ok = d.cards.filter((c) => c.url).length;
    const only = d.cards.length - ok;
    $('#pageInfo').textContent = `${d.cards.length} resultado(s) de Steam`;
    $('#prev').disabled = $('#next').disabled = true;
    renderGrid();
    banner(`${ok} con descarga en smods · ${only} solo en Steam (amplía el índice para descargarlos).`, '');
  } catch (e) {
    $('#grid').innerHTML = `<div class="empty">No se pudo buscar en Steam.<br><small>${esc(e.message)}</small></div>`;
  }
}

async function enrichPartial() {
  const partial = S.cards.filter((c) => c.partial);
  if (partial.length === 0) return;
  const urls = partial.map((c) => c.url);
  try {
    const d = await api('/api/enrich', { method: 'POST', body: { urls } });
    const byUrl = new Map(d.cards.map((x) => [x.url, x]));
    for (let i = 0; i < S.cards.length; i++) {
      const c = S.cards[i];
      if (byUrl.has(c.url)) {
        S.cards[i] = byUrl.get(c.url);
      }
    }
    renderGrid();
  } catch (e) {
    // fallar silenciosamente; el modal pide /api/mod si hace falta
    console.error('enrich falló', e);
  }
}

/* ── instalados ──────────────────────────────────────────────── */

const KIND_ES = {
  mod: 'Mod', asset: 'Asset', style: 'Estilo', theme: 'Tema',
  map: 'Mapa', scenario: 'Escenario', savegame: 'Partida guardada',
  unknown: 'sin clasificar',
};

function renderInstalled() {
  const box = $('#instList');
  const list = S.installed.filter((i) => {
    if (S.iFilter === 'enabled') return i.enabled;
    if (S.iFilter === 'disabled') return !i.enabled;
    if (S.iFilter === 'managed') return i.managed;
    return true;
  });

  if (!list.length) {
    box.innerHTML = `<div class="empty">Nada por aquí todavía.</div>`;
    return;
  }

  box.innerHTML = list.map((i) => {
    const img = i.workshop_id
      ? `<img loading="lazy" src="/api/image/${i.workshop_id}" alt=""
            onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'noimg',textContent:'📦'}))">`
      : `<div class="noimg" style="width:46px;height:46px;display:grid;place-items:center;font-size:20px">📦</div>`;
    return `
    <div class="row-item ${i.enabled ? '' : 'off'}" data-folder="${esc(i.folder)}" data-path="${esc(i.path)}">
      ${img}
      <div>
        <div class="t">${esc(i.title)}</div>
        <div class="s">
          ${esc(KIND_ES[i.kind] || i.kind)} · ${humanSize(i.size)}
          ${i.workshop_id ? ` · ID ${esc(i.workshop_id)}` : ''}
          · ${i.managed ? 'gestionado por skymods' : 'preexistente en el juego'}
          ${i.enabled ? '' : ' · <b>desactivado</b>'}
        </div>
        <div class="s" style="opacity:.75">${esc(i.path)}</div>
      </div>
      <div class="acts">
        <button data-act="toggle" data-enabled="${i.enabled}">
          ${i.enabled ? 'Desactivar' : 'Activar'}
        </button>
        <button class="danger" data-act="remove">Desinstalar</button>
      </div>
    </div>`;
  }).join('');

  $$('.row-item', box).forEach((el) => {
    const path = el.dataset.path;
    const folder = el.dataset.folder;
    $('[data-act="toggle"]', el)?.addEventListener('click', async (e) => {
      const to = e.target.dataset.enabled !== 'true';
      e.target.disabled = true;
      try {
        await api('/api/toggle', { method: 'POST', body: { folder, path, enabled: to } });
        toast(to ? 'Activado' : 'Desactivado',
          to ? 'La carpeta vuelve a la carpeta del juego.'
             : 'Movida fuera del juego. Cierra Cities: Skylines antes de tocar mods.');
        await refreshInstalled();
      } catch (err) { toast('No se pudo cambiar el estado', err.message, 'err'); e.target.disabled = false; }
    });

    $('[data-act="remove"]', el)?.addEventListener('click', async (e) => {
      if (!confirm(`¿Borrar "${folder}"?\n\nSe elimina de:\n${path}\n\nNo se puede deshacer.`)) return;
      e.target.disabled = true;
      try {
        await api('/api/remove', { method: 'POST', body: { folder, path } });
        toast('Desinstalado', folder, 'ok');
        await refreshInstalled();
        if (S.view === 'browse') loadBrowse(S.page);
      } catch (err) { toast('No se pudo borrar', err.message, 'err'); e.target.disabled = false; }
    });
  });
}

async function refreshInstalled() {
  try {
    const d = await api('/api/installed');
    S.installed = d.installed;
    $('#cntInstalled').textContent = d.installed.length;
    renderInstalled();
  } catch (e) { /* si el juego no esta, la vista lo dira */ }
}

/* ── modal ───────────────────────────────────────────────────── */

async function openModal(url) {
  $('#modal').hidden = false;
  $('#mTitle').textContent = 'Cargando…';
  $('#mImg').removeAttribute('src');
  $('#mBadges').innerHTML = '';
  $('#mMeta').innerHTML = '';
  $('#mActions').innerHTML = '';
  $('#mDesc').textContent = '';

  try {
    const d = await api(`/api/mod?url=${encodeURIComponent(url)}`);
    $('#mTitle').textContent = d.title || '(sin título)';

    if (d.workshop_id) {
      const im = $('#mImg');
      im.src = `/api/image/${d.workshop_id}`;
      im.onerror = () => { im.style.display = 'none'; };
      im.style.display = '';
    } else {
      $('#mImg').style.display = 'none';
    }

    const tags = [];
    tags.push(`<span class="tag info">${esc(KIND_ES[d.kind] || d.kind)}</span>`);
    if (d.compat_status === 'ok') tags.push(`<span class="tag ok">✔ compatible ${esc(d.compat)}</span>`);
    else if (d.compat_status === 'mismatch')
      tags.push(`<span class="tag warn">⚠ etiquetado ${esc(d.compat)}, tu juego ${esc(d.game_version)}</span>`);
    if (d.installed)
      tags.push(`<span class="tag installed">${d.installed.enabled ? 'instalado' : 'instalado pero desactivado'}</span>`);
    $('#mBadges').innerHTML = tags.join('');

    const rows = [
      ['Autor', d.author ? `${d.author}` : '—'],
      ['Tamaño', `${d.size_text || '—'}${d.size ? ` <span class="muted">(Steam: ${humanSize(d.size)})</span>` : ''}`],
      ['Última revisión', d.revision || '—'],
      ['Workshop ID', d.workshop_id || '—'],
    ];
    $('#mMeta').innerHTML = rows
      .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join('');

    const acts = [];
    if (d.installed) {
      acts.push(`<button class="danger" id="mRemove">Desinstalar</button>`);
      acts.push(`<button id="mToggle">${d.installed.enabled ? 'Desactivar' : 'Activar'}</button>`);
    } else if (d.kind === 'savegame') {
      // Una partida guardada no es un mod: no va en Files/ sino en la carpeta
      // de datos del juego, asi que skymods no la "instala". Ofrecer el boton
      // y fallar despues con "no hay ni DLL ni CRP" seria peor que decirlo.
      acts.push(`<button disabled title="No es un mod">no instalable</button>`);
    } else {
      acts.push(`<button class="primary" id="mInstall">Instalar</button>`);
    }
    $('#mActions').innerHTML = acts.join('');

    $('#mDesc').textContent = d.description || d.description_steam || 'Sin descripción.';
    // Ojo al orden: mLinks se reescribe entero, asi que la nota va despues.
    $('#mLinks').innerHTML =
      `Ficha: <a href="${esc(d.url)}" target="_blank" rel="noopener">smods.ru</a>` +
      (d.workshop_id ? ` · <a href="https://steamcommunity.com/workshop/filedetails/?id=${esc(d.workshop_id)}" target="_blank" rel="noopener">Steam Workshop</a>` : '');
    if (d.kind === 'savegame' && !d.installed) {
      $('#mLinks').insertAdjacentHTML(
        'beforeend',
        `<br><span class="warn-note">Es una partida guardada, no un mod. Para usarla,
         copiala a tu carpeta de partidas
         (<code>Documents/Colossal Order/Cities Skylines</code> en Windows,
         <code>…/Prefixes/pfx/drive_c/users/&lt;usuario&gt;/Documents</code> con Wine).</span>`
      );
    }

    $('#mInstall')?.addEventListener('click', () => doInstall(d));
    $('#mRemove')?.addEventListener('click', async () => {
      if (!confirm(`¿Borrar "${d.installed.folder}"? No se puede deshacer.`)) return;
      try {
        await api('/api/remove', { method: 'POST', body: { folder: d.installed.folder, path: d.installed.path } });
        toast('Desinstalado', d.installed.folder, 'ok');
        closeModal(); await refreshInstalled(); loadBrowse(S.page);
      } catch (e) { toast('No se pudo borrar', e.message, 'err'); }
    });
    $('#mToggle')?.addEventListener('click', async () => {
      const to = !d.installed.enabled;
      try {
        await api('/api/toggle', { method: 'POST', body: { folder: d.installed.folder, path: d.installed.path, enabled: to } });
        toast(to ? 'Activado' : 'Desactivado', '', 'ok');
        closeModal(); await refreshInstalled();
      } catch (e) { toast('No se pudo cambiar el estado', e.message, 'err'); }
    });
  } catch (e) {
    $('#mTitle').textContent = 'No se pudo abrir';
    $('#mDesc').textContent = e.message;
  }
}

function closeModal() { $('#modal').hidden = true; }

/* ── instalar (con progreso) ─────────────────────────────────── */

async function doInstall(d) {
  const t = toast('Instalando…', d.title);
  try {
    const { job } = await api('/api/install', { method: 'POST', body: { url: d.url } });
    pollJob(job.id, async (j) => {
      t.querySelector('.s').textContent = j.step || j.title;
      if (j.state === 'error') { t.remove(); toast('Falló la instalación', j.error, 'err'); }
      if (j.state === 'done') {
        t.className = 'toast ok';
        t.querySelector('.t').textContent = 'Instalado';
        const p = j.detail?.installed?.path || '';
        t.querySelector('.s').textContent = p;
        if (j.detail?.compat_warning) toast('Ojo con la compatibilidad', j.detail.compat_warning, 'warn');
        if (j.detail?.kind_mismatch) toast('Clasificación', j.detail.kind_mismatch, 'warn');
        closeModal(); await refreshInstalled(); loadBrowse(S.page);
      }
    });
  } catch (e) { t.remove(); toast('No se pudo iniciar', e.message, 'err'); }
}

function pollJob(id, cb, every = 900) {
  const tick = async () => {
    try {
      const j = await api(`/api/job/${id}`);
      cb(j);
      if (j.state === 'done' || j.state === 'error') return;
    } catch (e) { toast('Se perdió el seguimiento', e.message, 'err'); return; }
    setTimeout(tick, every);
  };
  tick();
}

/* ── índice ──────────────────────────────────────────────────── */

async function refreshIndexStats() {
  const d = await api('/api/state');
  const i = d.index;
  $('#idxStats').textContent =
    `${i.entries} mods · ${i.pages} páginas leídas · ${i.built_at || 'nunca'}` +
    (i.complete ? ' · catálogo completo' : '');
  if (!i.entries) {
    $('#idxBuild').textContent = 'Construir índice (empieza aquí)';
  }
}

$('#idxBuild')?.addEventListener('click', async () => {
  const pages = parseInt($('#idxPages').value, 10) || 100;
  const box = $('#idxProgress');
  box.hidden = false;
  $('#idxBuild').disabled = true;
  try {
    const { job } = await api('/api/index', { method: 'POST', body: { pages } });
    pollJob(job.id, async (j) => {
      box.querySelector('.bar').style.width = `${Math.round(j.progress * 100)}%`;
      box.querySelector('span').textContent = j.step || j.state;
      $('#idxStats').textContent = j.step || '';
      if (j.state === 'done') {
        toast('Índice listo', j.detail?.entries + ' mods', 'ok');
        $('#idxBuild').disabled = false;
        box.hidden = true;
        await refreshIndexStats();
      }
      if (j.state === 'error') {
        toast('Falló el indexado', j.error, 'err');
        $('#idxBuild').disabled = false;
      }
    }, 1200);
  } catch (e) { toast('No se pudo iniciar', e.message, 'err'); $('#idxBuild').disabled = false; }
});

/* ── navegación ──────────────────────────────────────────────── */

function switchView(v) {
  S.view = v;
  $$('.tab').forEach((t) => t.classList.toggle('is-active', t.dataset.view === v));
  $$('.view').forEach((s) => s.classList.toggle('is-active', s.id === `view-${v}`));
  if (v === 'installed') refreshInstalled();
  if (v === 'index') refreshIndexStats();
  if (v === 'browse' && !S.cards.length) loadBrowse(S.page);
}

$$('.tab').forEach((t) => t.addEventListener('click', () => switchView(t.dataset.view)));

$('#prev').addEventListener('click', () => loadBrowse(Math.max(1, S.page - 1)));
$('#next').addEventListener('click', () => loadBrowse(S.page + 1));

$$('.filters .chip[data-kind]').forEach((c) => c.addEventListener('click', () => {
  S.kind = c.dataset.kind;
  $$('.filters .chip[data-kind]').forEach((x) => x.classList.toggle('is-active', x === c));
  renderGrid();
}));

$$('.filters .chip[data-ifilter]').forEach((c) => c.addEventListener('click', () => {
  S.iFilter = c.dataset.ifilter;
  $$('.filters .chip[data-ifilter]').forEach((x) => x.classList.toggle('is-active', x === c));
  renderInstalled();
}));

$('#fHideInstalled').addEventListener('change', (e) => { S.hideInstalled = e.target.checked; renderGrid(); });
$('#fOnlyCompat').addEventListener('change', (e) => { S.onlyCompat = e.target.checked; renderGrid(); });

let searchTimer;
$('#q').addEventListener('input', (e) => {
  clearTimeout(searchTimer);
  const v = e.target.value.trim();
  if (!v) {
    $('#qClear').hidden = true;
    $('#qSteam').hidden = true;
    $('#pageInfo').textContent = `página ${S.page}`;
    $('#prev').disabled = $('#next').disabled = false;
    return loadBrowse(S.page);
  }
  searchTimer = setTimeout(() => {
    const sm = v.match(/(?:https?:\/\/)?smods\.ru\/archives\/(\d+)/);
    if (sm) { openModal(`https://smods.ru/archives/${sm[1]}`); return; }
    const st = v.match(/steamcommunity\.com\/(?:sharedfiles|workshop)\/filedetails\/\?id=(\d+)/);
    if (st) { resolveSteam(st[1]); return; }
    if (/^\d{9,12}$/.test(v)) { resolveSteam(v); return; }
    doSearch(v);
  }, 420);
});

async function resolveSteam(wid) {
  $('#qClear').hidden = false;
  $('#qSteam').hidden = false;
  try {
    const d = await api(`/api/resolve_steam?wid=${encodeURIComponent(wid)}`);
    if (d.resolved === 'smods' && d.card?.url) { openModal(d.card.url); return; }
    if (d.resolved === 'steam' && d.card) {
      const steamUrl = `https://steamcommunity.com/sharedfiles/filedetails/?id=${encodeURIComponent(wid)}`;
      banner(`<b>${esc(d.card.title)}</b> existe en Steam pero aún no está en tu índice local.`
        + ` <a href="${steamUrl}" target="_blank" rel="noopener">Ver en Steam</a>`
        + ` · amplía el índice (pestaña Índice) para instalarlo desde aquí.`, '');
      return;
    }
    banner(`Ese ID no existe en el Workshop. Revisa el número.`, 'err');
  } catch (e) {
    banner(`No se pudo resolver en Steam: ${esc(e.message)}`, 'err');
  }
}
$('#qClear').addEventListener('click', () => {
  $('#q').value = ''; $('#q').focus(); $('#q').dispatchEvent(new Event('input'));
});
$('#qSteam').addEventListener('click', () => {
  const v = $('#q').value.trim();
  if (v) doSearchOnline(v);
});

$('#modalClose').addEventListener('click', closeModal);
$('#modal').addEventListener('click', (e) => { if (e.target.id === 'modal') closeModal(); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { closeModal(); }
  if (e.key === '/' && document.activeElement !== $('#q')) { e.preventDefault(); $('#q').focus(); }
});

/* ── arranque ────────────────────────────────────────────────── */

(async function init() {
  try {
    const d = await api('/api/state');
    S.game = d.game;
    S.installed = d.installed;
    $('#cntInstalled').textContent = d.counts.installed;

    if (d.game) {
      $('#gameLine').innerHTML =
        `Cities: Skylines <b>${esc(d.game.version || '?')}</b> · ${esc(d.game.launcher || '?')}` +
        `<br><span style="opacity:.7">${esc(d.game.content_root)}</span>`;
      $('#installedPaths').textContent = `${d.counts.enabled} activos · ${d.counts.managed} gestionados por skymods`;
      const warn = (d.game.warnings || []).join(' ');
      if (warn) banner(warn);
      if (!d.index.entries) {
        banner((warn ? warn + ' ' : '') +
          'El índice de búsqueda está vacío: ve a la pestaña <b>Índice</b> y construye uno para poder buscar por nombre.', 'ok');
      }
    } else {
      $('#gameLine').textContent = 'No se encontró Cities: Skylines';
      banner('No se encontró la instalación del juego. Reinicia skymods con <code>--game-dir /ruta/a/CitiesSkylines</code>.', 'err');
    }
    renderInstalled();
    await refreshIndexStats();
  } catch (e) {
    banner('No se pudo hablar con el servidor: ' + esc(e.message), 'err');
  }
  loadBrowse(1);
})();
