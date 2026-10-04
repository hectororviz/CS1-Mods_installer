# CS1 Mods Installer

Gestor de mods para **Cities: Skylines** con interfaz web local. Instala desde
[smods.ru](https://smods.ru/) sin cuenta de Steam, sin el launcher y sin que
tengas que memorizar comandos.

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
| **Catálogo** | Explora los mods de smods.ru con carátulas, autor, tamaño y tags. |
| **Búsqueda** | Busca entre ~89.000 mods con un índice local. |
| **Instalar** | Descarga e instala en la carpeta correcta, según el contenido. |
| **Desactivar** | Mueve la carpeta aparte, sin tocar binarios. La vuelve a poner cuando quieras. |
| **Desinstalar** | Borra la carpeta y se olvida del mod. |
| **Compatibilidad** | Avisa si el mod es para otra versión de tu juego. |

Todo desde el navegador: skymods levanta un servidor solo en `127.0.0.1` y abre
la interfaz por su cuenta. No hay comandos que recordar.

## Instalación

Necesitas Python 3.11 o superior.

```bash
git clone https://github.com/TU-USUARIO/skymods
cd skymods

python3 -m venv .venv
.venv/bin/pip install -e .
```

## Uso

```bash
skymods
```

Eso es todo. Detecta el juego, levanta el servidor en `127.0.0.1:8787` y abre tu
navegador. Para pararlo, `Ctrl+C`.

Opciones:

```bash
skymods --game-dir ~/Games/Heroic/CitiesSkylines  # si la detección falla
skymods --port 9000                              # otro puerto
skymods --no-browser                            # no abrir el navegador
```

## Extensión de Chrome (instalar desde smods.ru)

En `extension/` hay una extensión sin publicar (Manifest V3) que pone un botón
verde **«⬇ Instalar en CS1»** en cada ficha de smods.ru. Al pulsarlo manda la
URL al backend local y muestra el progreso en el propio botón.

1. Abre `chrome://extensions`, activa el **modo desarrollador**.
2. **Cargar descomprimida** → elige la carpeta `extension/` de este repo.
3. Abre CS1 Mods Installer (el backend tiene que estar corriendo).
4. Entra en cualquier ficha, p. ej. `https://smods.ru/archives/52274`, y pulsa el botón.

Notas: la extensión solo habla con `127.0.0.1` (puertos 8787–8796, se
autodetecta); no necesita la Chrome Web Store porque se carga sin empaquetar.
No roba nada de Steam: reutiliza tu backend, que descarga de los mirrors.

Para dejarlo a un clic, crea un acceso en tu menú de aplicaciones:

```bash
mkdir -p ~/.local/share/applications
cat > ~/.local/share/applications/skymods.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Skymods
Comment=Gestor de mods para Cities: Skylines
Exec=/ruta/a/skymods/.venv/bin/skymods
Icon=applications-games
Terminal=false
Categories=Game;
EOF
```

## Dónde deja cada cosa

Esta es la parte que más confunde a la gente, así que va con explicación.

El contenido del juego **no** está en `Cities_Data/`, sino en **`Files/`**:

```
~/Games/Heroic/CitiesSkylines/        ← raíz de la instalación
├── launcher-settings.json           ← skymods lee aquí la versión
├── Cities_Data/                     ← ejecutable y datos, NO los mods
└── Files/                           ← aquí va todo el contenido
    ├── Mods/                        ← mods de código (DLL)
    │   ├── HardMode/
    │   └── 3810565217 Quay Tools/
    ├── Addons/
    │   ├── Assets/                  ← edificios, props (.crp)
    │   ├── Styles/
    │   └── MapThemes/
    ├── Maps/
    └── Scenarios/
```

Se deduced de los literales del propio juego: en `ColossalManaged.dll`_conviven
`Files`, `Addons`, `MapThemes`, `Styles`, `Assets`, `Mods` y las líneas de log
`"Addons path: "` / `"Mods path: "`.

**skymods decide el destino mirando el contenido del `.zip`**, no por el tag de
Steam:

| Contenido | Destino |
|---|---|
| `.dll` | `Files/Mods/<id> <Nombre>/` |
| `.crp` | `Files/Addons/Assets/<id> <Nombre>/` |
| `.style.xml` | `Files/Addons/Styles/<id> <Nombre>/` |

Gana el contenido: si un mod trae DLL y además assets, va a `Mods/`, porque lo
que el juego carga de verdad es la DLL. Si el tag de Steam y el archivo no
cuestan de acuerdo, skymods te lo dice en vez de elegir por los ojos cerrados.

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
> accesible sin autenticación. skymods lo trata como lo que es, un espejo, y lo
> compensa: compara el tamaño que declara smods con el que dice Steam y te
> avisa si el mirror parece viejo.

## Sobre `robots.txt`

El buscador de smods.ru es `GET /?s=...`, y su `robots.txt` **lo prohíbe**
(junto con `/category`, `/tag` y `/wp-content`). skymods no lo pide ni un solo
vez.

Lo que sí permite son las páginas de listado (`/page/N`), así que el buscador
se resuelve con un **índice local** que skymods construye leyéndolas. La web
dónde lo construyes: pestaña **Índice**. Empieza con 100 páginas y ve ampliando;
se reanuda donde se quedó.

Exigir este límite es algo que la mayoría de scrapers se salta. Aquí es
explícito: el parser de robots se carga al arrancar, se cachea, y se consulta
**antes** de cada petición a smods.ru.

## Desactivar = mover la carpeta

El launcher guarda la lista de mods activados en `userGameState.cgs`, un binario
con formato propietario (CGSF). Editarlo a ciegas es una forma excelente de
corromper la configuración del juego.

Así que "desactivar" mueve la carpeta a
`~/.local/state/skymods/disabled/`. El juego deja de verla y sigue intacto;
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
Google no sirven (no traen títulos), así que no hay atajo. Va en
`~/.cache/skymods/index.json`.

**Carátulas.** Steam sirve las imágenes como PNG de 1000×1000 (~770 KB). Bajarlas
por cada mod sería un desastre, así que se descargan **bajo demanda**, se
recortan a cuadrado y se guardan como WebP de 420×420: **20 KB**. La segunda
visita se sirve desde disco en ~50 ms.

**Velocidad.** Leer 10 fichas en serie son ~49 s. Con 6 hilos baja a ~12 s, y a
los ~3 s gracias a la caché en memoria. El pool es deliberadamente pequeño:
rápido sin parecer un escáner.

**Clasificación.** El vocabulario de tags no está inventado: se extrajo
muestreando 244 items reales del Workshop. Salen 38 tags distintos, todos en
singular (`Vehicle`, no `vehicles`). Se declara en `steam.KINDS`, y un test
comprueba que la web tiene un filtro para cada uno.

## Estructura

```
skymods/
├── skymods/
│   ├── config.py      rutas, ajustes, detección del juego
│   ├── smods.py       scraping de smods.ru + robots.txt
│   ├── steam.py       metadatos anónimos: tags, tamaño, compatibilidad
│   ├── modsbase.py    descarga en 3 pasos
│   ├── installer.py   extraer, clasificar, instalar, borrar, activar
│   ├── index.py       índice local de búsqueda
│   ├── images.py      caché de carátulas
│   ├── catalog.py     une todo; decisiones de producto
│   ├── jobs.py        tareas en segundo plano con progreso
│   ├── server.py      API + sirve la interfaz
│   └── web/           HTML, CSS y JS sin frameworks
└── tests/
```

## Desarrollo

```bash
.venv/bin/python tests/test_skymods.py   # 43 tests
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
  tamaños, pero skymods no puede saberlo con certeza sin autenticar en Steam.
- Sin instalación de partidas guardadas: no son mods (no van en `Files/`), así
  que la web lo dice en vez de ofrecer un botón que falla.
- El índice completo son 8.900 peticiones. Empieza con 100 y amplía según lo que
  necesites.

## Licencia

MIT.