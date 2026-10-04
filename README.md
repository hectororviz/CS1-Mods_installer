# CS1 Mods Installer

Gestor de mods para **Cities: Skylines** con extensión de Chrome, interfaz web
local y TUI de terminal. Instala desde [smods.ru](https://smods.ru/) sin cuenta
de Steam, sin el launcher y sin que tengas que memorizar comandos.

---

## Por qué existe

Si jugaste a Cities: Skylines con **Epic Games / GOG bajo Heroic**, seguro que
te ha pasado esto: en el launcher hay una opción llamada literalmente
`steamWorkshopDisabled`, así que la lista de mods aparece vacía. Los Steam
Workshop solo se pueden instalar desde Steam, y si copias la carpeta a mano el
juego no la ve.

La respuesta habitual es "instálate Steam". CS1 Mods Installer existe para que
no haga falta.

**No es un mod más: no modifica nada del juego.** No toca DLLs del juego, ni
`userGameState.cgs`, ni el launcher. Solo coloca carpetas en los directorios
correctos y las mueve de sitio.

## Qué hace

| | |
|---|---|
| **Extensión de Chrome** | Navegas smods.ru e instalas con un clic, con progreso en el botón. |
| **Web local** | Administra lo instalado: activar, desactivar, desinstalar. |
| **TUI** | Todo lo anterior desde la terminal, en texto puro (más rápida). |
| **Búsqueda online** | El Workshop de Steam para encontrar, los mirrors para descargar. |
| **Pegar enlace o ID** | Una URL de smods/Steam o un ID numérico abren la ficha directa. |
| **Compatibilidad** | Avisa si el mod es para otra versión de tu juego. |

Todo pasa por un servidor solo en `127.0.0.1`. No hay comandos que recordar.

## Instalación

Necesitas Python 3.11 o superior.

```bash
git clone https://github.com/hectororviz/CS1-Mods_installer.git
cd CS1-Mods_installer

python3 -m venv .venv
.venv/bin/pip install -e .
```

Esto deja tres comandos: `cs1-mods-installer` (también `cs1mods`) para el
backend + web, y `cs1-mods-tui` para la terminal.

## Uso

```bash
cs1-mods-installer
```

Eso es todo. Detecta el juego y levanta el servidor en `127.0.0.1:8787`. Para pararlo, `Ctrl+C`.

> Si lo abres desde el menú de aplicaciones, arranca en silencio (sin abrir el
> navegador): el icono del menú lleva `--no-browser`. Abre el gestor con el
> popup de la extensión o en `http://127.0.0.1:8787`.

Opciones:

```bash
cs1-mods-installer --game-dir ~/Games/Heroic/CitiesSkylines  # si la detección falla
cs1-mods-installer --port 9000                              # otro puerto
cs1-mods-installer --no-browser                             # no abrir el navegador
cs1-mods-installer --tui                                    # interfaz de terminal en vez de web
```

## TUI (terminal)

```bash
cs1-mods-tui
```

Texto puro: sin navegador, sin imágenes. La tabla pinta en ~1 s con los títulos
y completa tipo/tamaño/autor en segundo plano.

| Tecla | Acción |
|---|---|
| `/` | buscar en el índice local |
| `F2` | buscar online en Steam |
| `Enter` | abrir ficha / activar-desactivar |
| `Esc` | cerrar ficha |
| `n` / `p` | página siguiente / anterior |
| `1` / `2` | Catálogo / Instalados |
| `r` | recargar |
| `q` | salir |

Pegar un enlace de smods/Steam o un ID en la búsqueda abre la ficha directa,
igual que en la web.

## Cómo encontrar un mod

Tres caminos, de más a menos inmediato:

1. **Extensión**: lo ves en smods.ru → botón verde → instalado.
2. **Pegar enlace o ID**: `https://smods.ru/archives/52274`, un enlace del
   Workshop o `1637663252` en el buscador de la web o la TUI. Si el mod tiene
   página indexada se abre instalable; si no, se avisa.
3. **Buscar por nombre**: índice local (rápido, cubre lo indexado) o Steam 🌐 /
   `F2` (online, siempre completo; lo instalable se verifica por workshop ID
   para no enlazar la ficha equivocada).

## Extensión de Chrome (descubrir e instalar desde smods.ru)

El flujo principal es la extensión: navegas smods.ru con normalidad e instalas
con un clic. La web solo administra lo ya instalado.

En `extension/` hay una extensión sin publicar (Manifest V3):

- **Botón flotante** en cada ficha de smods.ru: **«⬇ Instalar en CS1»**, con
  progreso en el propio botón.
- **Popup** (clic en el icono): estado del backend, cuántos mods hay
  instalados/indexados, botón **Abrir gestor** y botón **Ampliar índice**.

1. Abre `chrome://extensions`, activa el **modo desarrollador**.
2. **Cargar descomprimida** → elige la carpeta `extension/` de este repo.
3. Abre CS1 Mods Installer (el backend tiene que estar corriendo).
4. Entra en cualquier ficha, p. ej. `https://smods.ru/archives/52274`, y pulsa el botón.

Tras instalar o cambiar la extensión, recárgala en `chrome://extensions` (↻).

Notas: la extensión solo habla con `127.0.0.1` (puertos 8787–8796, se
autodetecta); no necesita la Chrome Web Store porque se carga sin empaquetar.
No roba nada de Steam: reutiliza tu backend, que descarga de los mirrors.

Para dejarlo a un clic, crea un acceso en tu menú de aplicaciones:

```bash
mkdir -p ~/.local/share/applications
cat > ~/.local/share/applications/cs1-mods-installer.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=CS1 Mods Installer
Comment=Gestor de mods para Cities: Skylines
Exec=/ruta/a/CS1-Mods_installer/.venv/bin/cs1-mods-installer --no-browser
Icon=applications-games
Terminal=false
Categories=Game;
EOF
```

## Dónde deja cada cosa

Esta es la parte que más confunde a la gente, así que va con explicación.

`<instalacion>/Files/` es **solo el contenido de fábrica** (`HardMode`, `UnlimitedMoney`...). Los mods de usuario **no van ahí**: el juego los lee del perfil del jugador. Lo confirma el propio `output_log.txt`, que carga `userGameState.cgs` desde `C:\users\...\AppData\Local\Colossal Order\Cities_Skylines`.

```
~/Games/Heroic/CitiesSkylines/                  ← instalación (NO tocar)
└── Files/Mods/                                 ← solo fábrica (HardMode...)

~/Games/Heroic/Prefixes/pfx/drive_c/users/steamuser/AppData/Local/
└── Colossal Order/Cities_Skylines/              ← AQUÍ van tus mods
    └── Addons/
        ├── Mods/                               ← mods de código (.dll)
        │   └── 3810565217 Quay Tools/
        ├── Assets/                             ← edificios, props (.crp)
        ├── Styles/
        └── MapThemes/
```

En Linux nativo es `~/.local/share/Colossal Order/Cities_Skylines/` con la misma estructura `Addons/...`.

**CS1 Mods Installer decide el destino mirando el contenido del `.zip`**, no por el tag de
Steam:

| Contenido | Destino |
|---|---|
| `.dll` | `Addons/Mods/<id> <Nombre>/` |
| `.crp` | `Addons/Assets/<id> <Nombre>/` |
| `.style.xml` | `Addons/Styles/<id> <Nombre>/` |

Gana el contenido: si un mod trae DLL y además assets, va a `Mods/`, porque lo
que el juego carga de verdad es la DLL. Si el tag de Steam y el archivo no
están de acuerdo, se te dice en vez de elegir a ojos cerrados.

## Cómo consigue los archivos

Steam no deja descargar los ficheros del Workshop sin su sesión: lo
comprobamos, `file_url` viene **vacío en los 30** items que probamos, y
`steamcmd +login anonymous` falla. Así que el camino es otro:

```
smods.ru/archives/<id>          ficha: título, autor, tamaño, enlace
        ↓
modsbase.com/<code>/<id>.zip     página con botón
        ↓  POST op=download2&id=<code>
URL prefirmada de S3              X-Amz-Signature, caduca en ~1 h
        ↓
el .zip
```

Sin captcha, sin cuenta, sin cookies de sesión. De la **API pública de Steam**
solo se leen *metadatos* (tags, tamaño, carátula), que sí son anónimos y sirven
para clasificar y avisar de compatibilidad.

> **Por qué smods.ru y no el Workshop.** No es capricho: es la única fuente
> accesible sin autenticación. Se la trata como lo que es, un espejo, y se
> compensa: compara el tamaño que declara smods con el que dice Steam y te
> avisa si el mirror parece viejo.

## Sobre `robots.txt`

El buscador de smods.ru es `GET /?s=...`, y su `robots.txt` **lo prohíbe**
(junto con `/category`, `/tag` y `/wp-content`). No se pide ni una sola vez.

Lo que sí permite son las páginas de listado (`/page/N`), así que el buscador
local se resuelve con un **índice** que se construye leyéndolas: botón
**Ampliar índice** en el popup de la extensión (100 páginas por tanda).
Empieza con poco y ve ampliando; se reanuda donde se quedó y cada página
reintenta ante cortes de red.

Exigir este límite es algo que la mayoría de scrapers se salta. Aquí es
explícito: el parser de robots se carga al arrancar, se cachea, y se consulta
**antes** de cada petición a smods.ru.

## Desactivar = mover la carpeta

El launcher guarda la lista de mods activados en `userGameState.cgs`, un binario
con formato propietario (CGSF). Editarlo a ciegas es una forma excelente de
corromper la configuración del juego.

Así que "desactivar" mueve la carpeta a
`~/.local/state/cs1-mods-installer/disabled/`. El juego deja de verla y sigue intacto;
"activar" la devuelve. Cierra el juego antes, o el cambio no aparecerá hasta la
próxima vez.

## Seguridad

Lo que se descarga de internet va a parar en tu disco, así que:

- Se rechaza cualquier ruta absoluta, `../` y symlinks dentro del `.zip`
  **antes** de escribir un solo byte.
- Se comprueba que cada ruta resuelta siga dentro del directorio destino.
- Techo de 4 GiB descomprimido, por si acaso.
- Se extrae a un temporal y se mueve al destino con `rename`: una descarga
  corrupta nunca deja el juego a medias.
- Desinstalar **solo** borra si la carpeta está dentro de `Files/`, nunca fuera.
- Los títulos vienen del `<h1>` de smods.ru, o sea texto libre de terceros, así
  que se sanean antes de convertirse en nombre de carpeta. (Un `<h1>` con
  `../../` se colaba en el camino; lo cazó un test.)

El servidor escucha **solo en `127.0.0.1`**. No es accesible desde la red.

## Detalles de implementación

**Índice.** ~89.000 mods, 10 por página: unas 8.900 peticiones. Los sitemaps de
Google no sirven (no traen títulos), así que no hay atajo. Se construye en
lotes paralelos (4 hilos), reanudable, y va en
`~/.cache/cs1-mods-installer/index.json`.

**Fichas.** Las fichas de smods se cachean en memoria y en disco
(`details.json`, TTL 14 días): la segunda visita no toca la red.

**Carátulas.** Steam sirve las imágenes como PNG de 1000×1000 (~770 KB). Bajarlas
por cada mod sería un desastre, así que se descargan **bajo demanda**, se
recortan a cuadrado y se guardan como WebP de 420×420: **20 KB**. La segunda
visita se sirve desde disco en ~50 ms.

**Velocidad.** La web y la TUI pintan primero la lista parcial (títulos del
índice, ~1 s) y completan metadatos en segundo plano. El pool de detalle es
deliberadamente pequeño (6 hilos + HTTP/2 con keepalive): rápido sin parecer
un escáner.

**Búsqueda online.** El `robots.txt` de `steamcommunity.com` solo prohíbe rutas
administrativas, así que el buscador del Workshop se puede leer anónimamente.
Da títulos e IDs exactos al instante; el cruce con el índice local se verifica
por workshop ID para no enlazar la ficha equivocada. De Steam nunca sale un
byte descargable: solo metadatos.

**Clasificación.** El vocabulario de tags no está inventado: se extrajo
muestreando 244 items reales del Workshop. Salen 38 tags distintos, todos en
singular (`Vehicle`, no `vehicles`). Se declara en `steam.KINDS` y hay tests
que lo cubren.

## Estructura

```
CS1-Mods_installer/
├── cs1_mods_installer/
│   ├── config.py      rutas, ajustes, detección del juego
│   ├── smods.py       scraping de smods.ru + robots.txt
│   ├── steam.py       metadatos y búsqueda anónima del Workshop
│   ├── modsbase.py    descarga en 3 pasos
│   ├── installer.py   extraer, clasificar, instalar, borrar, activar
│   ├── index.py       índice local de búsqueda (paralelo, reanudable)
│   ├── images.py      caché de carátulas
│   ├── catalog.py     une todo; decisiones de producto
│   ├── jobs.py        tareas en segundo plano con progreso
│   ├── server.py      API + sirve la interfaz
│   ├── tui.py         interfaz de terminal (Textual)
│   └── web/           HTML, CSS y JS sin frameworks
├── extension/         extensión de Chrome (Manifest V3)
└── tests/
    ├── test_skymods.py  unitarios (stdlib)
    └── ui_contract.mjs  contrato web/HTML/servidor
```

## Desarrollo

```bash
.venv/bin/python tests/test_skymods.py   # 52 tests
node tests/ui_contract.mjs               # contrato web/HTML/servidor
```

El primero cubre lo que no se ve al usar la web: que un zip no pueda escribir
fuera del juego, que el destino se elija por el contenido, que no se borre
fuera de `Files/`.

El segundo evita el fallo típico de mantener HTML, CSS y JS por separado: que
el script pida un `#id`, una clase o una ruta que ya no existe. También avisa de
filtros que nunca filtrarían nada y de `innerHTML` con datos de red sin escapar.

## Límites conocidos

- El catálogo de smods.ru cambia: si mañana cambia el HTML de las fichas, hay
  que actualizar los selectores de `smods.py`.
- Los mirrors de smods pueden estar desactualizados. Se avisa comparando
  tamaños, pero no se puede saber con certeza sin autenticar en Steam.
- Sin instalación de partidas guardadas: no son mods (no van en `Files/`), así
  que la web lo dice en vez de ofrecer un botón que falla.
- El índice completo son 8.900 peticiones. Empieza con 100 y amplía según lo que
  necesites.

## Licencia

MIT.