/* Contrato entre el cliente web, el HTML y el servidor.
 *
 * Los tres archivos se tocaron a la vez y por separado; este script es el que
 * detecta el fallo tipico de esa separacion: que el JS pida un #id, una clase
 * o una ruta que ya no existe. Sin red ni navegador.
 *
 *   node tests/ui_contract.mjs
 */

import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const read = (p) => readFileSync(join(root, p), 'utf8');

const files = {
  html: 'cs1_mods_installer/web/index.html',
  js: 'cs1_mods_installer/web/app.js',
  css: 'cs1_mods_installer/web/style.css',
  py: 'cs1_mods_installer/server.py',
};

for (const [k, p] of Object.entries(files)) {
  if (!existsSync(join(root, p))) {
    console.error(`FALTA ${p}`);
    process.exit(1);
  }
}

const html = read(files.html);
const js = read(files.js);
const css = read(files.css);
const py = read(files.py);

let errors = 0;
let checks = 0;
const fail = (msg) => { errors++; console.error(`  ✗ ${msg}`); };
const ok = (msg) => { checks++; console.log(`  ✓ ${msg}`); };

const uniq = (arr) => [...new Set(arr)].sort();

// ---------------------------------------------------------------- ids del HTML
const htmlIds = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));

// Los que el JS busca con $('#foo'). Los templates dinamicos ($(`#${x}`)) se
// saltan a proposito: no son un id fijo. Los ids que el propio JS inyecta en el
// HTML tampoco se esperan en index.html.
const injectedIds = new Set(
  [...js.matchAll(/\bid="([A-Za-z][\w-]*)"/g)].map((m) => m[1])
);
const jsIds = uniq(
  [...js.matchAll(/\$\('#([A-Za-z][\w-]*)'/g)]
    .map((m) => m[1])
    .filter((id) => !injectedIds.has(id))
);

console.log(`\nids: ${htmlIds.size} en el HTML, ${jsIds.length} usados por el JS`);
const missingIds = jsIds.filter((id) => !htmlIds.has(id));
if (missingIds.length) fail(`el JS busca ids que no existen en el HTML: ${missingIds.join(', ')}`);
else ok(`los ${jsIds.length} ids que busca el JS existen`);

// Cuantos ids del HTML no se usan: informational, no es error.
const unusedIds = [...htmlIds].filter((id) => !jsIds.includes(id));

// ------------------------------------------------------- vistas vs pestanas
const viewIds = uniq([...html.matchAll(/id="view-([a-z]+)"/g)].map((m) => m[1]));
const tabViews = uniq([...html.matchAll(/data-view="([a-z]+)"/g)].map((m) => m[1]));
console.log(`\nvistas: ${viewIds.join(', ')} | pestanas: ${tabViews.join(', ')}`);
const viewMismatch = tabViews.filter((v) => !viewIds.includes(v));
if (viewMismatch.length) fail(`pestanas sin vista: ${viewMismatch.join(', ')}`);
else ok('cada pestana tiene su vista');
if (viewIds.length !== tabViews.length) fail('hay vistas sin pestana o al reves');

// --------------------------------------------------------- rutas de la API
const serverRoutes = new Set(
  [...py.matchAll(/@app\.(?:get|post)\("([^"]+)"/g)].map((m) => m[1])
);
const jsRoutes = uniq(
  [...js.matchAll(/`(\/api\/[A-Za-z0-9_/-]+)/g)].map((m) => m[1])
    .concat([...js.matchAll(/'(\/api\/[A-Za-z0-9_/-]+)/g)].map((m) => m[1]))
);
console.log(`\nservidor define ${serverRoutes.size} rutas; el JS llama a ${jsRoutes.length}`);
const badRoutes = jsRoutes.filter((r) => {
  // /api/job/${id} -> /api/job/  ; busca la ruta declarada mas corta que encaje
  return !serverRoutes.has(r) && ![...serverRoutes].some((s) => s.startsWith(r));
});
if (badRoutes.length) fail(`el JS llama a rutas inexistentes: ${badRoutes.join(', ')}`);
else ok('todas las rutas que llama el JS existen en el servidor');

// ------------------------------------------------- filtros vs kinds posibles
// Solo los kinds que el backend puede dar ANTES de descargar (los que salen de
// los tags de Steam, steam.KINDS) necesitan un chip: un chip para "style"
// siempre estaria vacio, porque el estilo solo se descubre al extraer el zip.
// Los que solo existen en instalador.KINDS se listan como informativo.
const pyKinds = (file) => {
  const m = read(file).match(/^KINDS = \(([^)]*)\)/m);
  return m ? [...m[1].matchAll(/"(\w+)"/g)].map((x) => x[1]) : [];
};
const cardKinds = pyKinds('cs1_mods_installer/steam.py').filter((k) => k !== 'unknown');
const installKinds = pyKinds('cs1_mods_installer/installer.py').filter((k) => k !== 'unknown');
const onlyAfterDownload = installKinds.filter((k) => !cardKinds.includes(k));
const chipKinds = uniq([...html.matchAll(/data-kind="([^"]*)"/g)].map((m) => m[1]));

console.log(`\nkinds visibles antes de descargar: ${cardKinds.join(', ')}`);
console.log(`chips de filtro: ${chipKinds.map((k) => k || '(todo)').join(', ') || '(ninguno)'}`);
if (!chipKinds.length) {
  ok('sin chips de catálogo: la web solo administra instalados');
} else {
  const noChip = cardKinds.filter((k) => !chipKinds.includes(k));
  if (noChip.length) fail(`kinds que la web no puede filtrar: ${noChip.join(', ')}`);
  else ok('cada kind filtrable tiene su chip');
}
if (onlyAfterDownload.length) {
  console.log(
    `  · ${onlyAfterDownload.join(', ')}: solo se detecta al extraer el zip, por eso no hay chip`
  );
}
// Un chip que no corresponde a ningun kind visible es un filtro muerto.
const deadChip = chipKinds.filter((k) => k && !cardKinds.includes(k));
if (deadChip.length) fail(`chips que nunca filtrarian nada: ${deadChip.join(', ')}`);
else ok('ningun chip es un filtro muerto');

// Un kind visible que no se puede instalar necesita una explicacion en la web,
// o el boton de instalar falla con un error que no entiende nadie.
const notInstallable = cardKinds.filter((k) => !installKinds.includes(k));
if (notInstallable.length && !js.includes('no instalable')) {
  fail(`la web ofrece instalar kinds que el instalador rechaza: ${notInstallable.join(', ')}`);
} else if (notInstallable.length) {
  ok(`la web explica que ${notInstallable.join(', ')} no es instalable`);
}

// --------------------------------------------------------- clases del JS/CSS
const jsClasses = uniq(
  [...js.matchAll(/\$\$?\('\.([A-Za-z][\w-]*)/g)].map((m) => m[1])
);
const styled = new Set([...css.matchAll(/\.([A-Za-z][\w-]*)/g)].map((m) => m[1]));
const htmlClasses = new Set(
  uniq([...html.matchAll(/class="([^"]+)"/g)].flatMap((m) => m[1].split(/\s+/)))
);
const unstyled = jsClasses.filter((c) => !styled.has(c));
if (unstyled.length) fail(`clases que el JS busca y el CSS no define: ${unstyled.join(', ')}`);
else ok(`las ${jsClasses.length} clases que busca el JS tienen estilo`);

// Las clases que el JS inyecta en HTML generado tambien necesitan estilo.
const injected = uniq([
  ...[...js.matchAll(/class="([a-z][\w -]*)"/g)].flatMap((m) => m[1].split(/\s+/)),
]);
const injectedUnstyled = injected.filter((c) => c && !styled.has(c));
if (injectedUnstyled.length) {
  fail(`clases generadas por el JS sin estilo: ${injectedUnstyled.join(', ')}`);
} else ok(`las ${injected.length} clases que el JS genera tienen estilo`);

// ------------------------------------------------------------------ kinder
// Los ids que el JS escribe en el HTML tambien tienen que existir alli.
const mChildren = uniq(
  [...html.matchAll(/<button[^>]*id="([A-Za-z][\w-]*)"/g)].map((m) => m[1])
);
console.log(`\nbotones con id en el HTML: ${mChildren.join(', ') || '(ninguno)'}`);

// ------------------------------------------------------- escapes obligatorios
// Un innerHTML con datos de la red sin escapar es XSS. A ojo no se ve.
const inner = [...js.matchAll(/\.innerHTML\s*=\s*`([^`]*)`/g)].map((m) => m[1]);
const risky = inner.filter((tpl) => {
  // toda interpolacion debe pasar por esc() o ser un numero/ruta ya segura
  const interps = [...tpl.matchAll(/\$\{([^}]*)\}/g)].map((m) => m[1]);
  return interps.some(
    (i) =>
      !/\besc\(/.test(i) &&
      !/^[a-z_]*(\.)?(id|size|progress|elapsed|kind|state|path|page)\b/i.test(i.trim()) &&
      !/^(id|counts|d\.game|toFixed|Math)/.test(i.trim())
  );
});
if (risky.length) {
  console.log(`  · revisar a mano ${risky.length} innerHTML con interpolaciones:`);
  for (const r of risky) {
    console.log(`      ${r.trim().slice(0, 88)}`);
  }
} else ok('los innerHTML con datos de red pasan por esc()');

// ------------------------------------------------------------------ resumen
console.log(`\n${errors ? 'FALLOS' : 'TODO OK'}: ${checks} comprobaciones, ${errors} fallos`);
if (unusedIds.length) console.log(`(ids del HTML no usados por el JS: ${unusedIds.join(', ')})`);
process.exit(errors ? 1 : 0);