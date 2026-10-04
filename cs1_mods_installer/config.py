"""Rutas, ajustes y deteccion de la instalacion de Cities: Skylines."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

APP_NAME = "cs1-mods-installer"
APP_TITLE = "CS1 Mods Installer"
STEAM_APPID = "255710"  # Cities: Skylines (CS1)

# Hosts
SMODS_BASE = "https://smods.ru"
MODSBASE_RE = re.compile(r"^https://modsbase\.com/", re.I)
STEAM_API = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) CS1-Mods_installer/1.0 (+gestor de mods para Cities: Skylines)"
)

# Subcarpetas de contenido que el juego lee dentro de <instalacion>/Files
CONTENT_ROOT_NAME = "Files"
ASSET_SUBDIRS = ("Addons/Assets", "Addons/Styles", "Addons/MapThemes")


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / APP_NAME


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / APP_NAME


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    return Path(base) / APP_NAME


def image_cache_dir() -> Path:
    return cache_dir() / "img"


def index_path() -> Path:
    return cache_dir() / "index.json"


def manifest_path() -> Path:
    return state_dir() / "installed.json"


def disabled_root() -> Path:
    """Donde se mueven los mods deshabilitados."""
    return state_dir() / "disabled"


def settings_path() -> Path:
    return config_dir() / "config.json"


def ensure_dirs() -> None:
    for d in (config_dir(), cache_dir(), state_dir(), image_cache_dir()):
        d.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# Ajustes
# --------------------------------------------------------------------------


def load_settings() -> dict[str, Any]:
    p = settings_path()
    if p.is_file():
        try:
            return json.loads(p.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_settings(data: dict[str, Any]) -> None:
    ensure_dirs()
    settings_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")


# --------------------------------------------------------------------------
# Deteccion de la instalacion del juego
# --------------------------------------------------------------------------


@dataclass
class GameInstall:
    """Instalacion de Cities: Skylines detectada en disco."""

    install_dir: Path
    content_root: Path  # <instalacion>/Files (contenido de fabrica, solo referencia)
    user_dir: Path | None = None  # .../Colossal Order/Cities_Skylines (donde el juego lee los mods)
    version: str = ""  # p.ej. 1.21.1-f9
    app_id: str = ""  # p.ej. cities_v2 en el launcher
    launcher: str = ""  # epic / steam / desconocido
    source: str = ""  # de donde salio elajuste
    warnings: list[str] = field(default_factory=list)

    # --- rutas de destino -------------------------------------------------
    # OJO: los mods de usuario NO van en <instalacion>/Files/Mods (ahi solo
    # viven los mods de fabrica: HardMode, UnlimitedMoney...). El juego los
    # lee de %LOCALAPPDATA%/Colossal Order/Cities_Skylines/Addons/Mods,
    # que bajo Heroic/Wine es <...>/Prefixes/pfx/drive_c/users/.../AppData/...
    # y en Linux nativo ~/.local/share/Colossal Order/Cities_Skylines.
    def _user(self) -> Path:
        if self.user_dir is not None:
            return self.user_dir
        # Compatibilidad con tests viejos: antes se usaba Files/ directo.
        return self.content_root

    @property
    def mods_dir(self) -> Path:
        """Mods de codigo (DLL)."""
        if self.user_dir is not None:
            return self.user_dir / "Addons" / "Mods"
        return self.content_root / "Mods"

    @property
    def assets_dir(self) -> Path:
        """Assets (.crp): edificios, props, redes."""
        if self.user_dir is not None:
            return self.user_dir / "Addons" / "Assets"
        return self.content_root / "Addons" / "Assets"

    @property
    def styles_dir(self) -> Path:
        if self.user_dir is not None:
            return self.user_dir / "Addons" / "Styles"
        return self.content_root / "Addons" / "Styles"

    @property
    def map_themes_dir(self) -> Path:
        if self.user_dir is not None:
            return self.user_dir / "Addons" / "MapThemes"
        return self.content_root / "Addons" / "MapThemes"

    @property
    def maps_dir(self) -> Path:
        if self.user_dir is not None:
            return self.user_dir / "Maps"
        return self.content_root / "Maps"

    @property
    def scenarios_dir(self) -> Path:
        if self.user_dir is not None:
            return self.user_dir / "Scenarios"
        return self.content_root / "Scenarios"

    def to_dict(self) -> dict[str, Any]:
        return {
            "install_dir": str(self.install_dir),
            "content_root": str(self.content_root),
            "user_dir": str(self.user_dir) if self.user_dir else "",
            "version": self.version,
            "app_id": self.app_id,
            "launcher": self.launcher,
            "source": self.source,
            "warnings": list(self.warnings),
            "paths": {
                "mods": str(self.mods_dir),
                "assets": str(self.assets_dir),
                "styles": str(self.styles_dir),
                "map_themes": str(self.map_themes_dir),
                "maps": str(self.maps_dir),
                "scenarios": str(self.scenarios_dir),
            },
        }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text("utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}


def _looks_like_install(d: Path) -> bool:
    """Una instalacion valida tiene el ejecutable del juego y/o app.info."""
    return (d / "Cities.exe").is_file() or (d / "Cities_Data" / "app.info").is_file()


def _candidate_dirs() -> list[Path]:
    home = Path.home()
    out: list[Path] = []
    # Heroic (Epic/GOG) en la ubicacion por defecto de este setup
    heroic = home / "Games" / "Heroic"
    if heroic.is_dir():
        out.extend(sorted(p for p in heroic.iterdir() if p.is_dir() and p.name != "Prefixes"))
    # Steam en Linux
    for steam_root in (
        home / ".steam" / "steam" / "steamapps" / "common",
        home / ".local" / "share" / "Steam" / "steamapps" / "common",
    ):
        cs = steam_root / "Cities_Skylines"
        if cs.is_dir():
            out.append(cs)
    # Buzon de salida generico
    out.extend(sorted(p for p in (home / "Games").glob("*") if p.is_dir()))
    return out


def _find_user_dir(install_dir: Path) -> tuple[Path, list[str]]:
    """Localiza .../Colossal Order/Cities_Skylines donde el juego lee los mods.

    Devuelve (ruta, avisos). En Windows es %LOCALAPPDATA%/Colossal Order/...;
    bajo Heroic/Wine cuelga del prefijo, y en Linux nativo de ~/.local/share.
    """
    home = Path.home()
    warnings: list[str] = []
    candidates: list[Path] = []

    # 1. Prefijo Wine junto a la instalacion: <Games/Heroic>/Prefixes/pfx/...
    for base in (install_dir.parent / "Prefixes", home / "Games" / "Heroic" / "Prefixes"):
        for user in ("steamuser", "steam", os.environ.get("USER", "")):
            if not user:
                continue
            for pfx in (base / "pfx", base / "shared" / "pfx"):
                candidates.append(
                    pfx / "drive_c" / "users" / user / "AppData" / "Local"
                    / "Colossal Order" / "Cities_Skylines"
                )
    # 2. Cualquier otro usuario dentro de esos prefijos (por si el nombre cambia)
    for base in (install_dir.parent / "Prefixes", home / "Games" / "Heroic" / "Prefixes"):
        for pfx in (base / "pfx", base / "shared" / "pfx"):
            users_dir = pfx / "drive_c" / "users"
            if users_dir.is_dir():
                for u in sorted(users_dir.iterdir()):
                    if u.is_dir() and u.name not in ("Public",):
                        candidates.append(
                            u / "AppData" / "Local" / "Colossal Order" / "Cities_Skylines"
                        )
    # 3. Wine generico
    candidates.append(
        home / ".wine" / "drive_c" / "users" / os.environ.get("USER", "steamuser")
        / "AppData" / "Local" / "Colossal Order" / "Cities_Skylines"
    )
    # 4. Linux nativo (Steam)
    candidates.append(home / ".local" / "share" / "Colossal Order" / "Cities_Skylines")

    seen: set[str] = set()
    for c in candidates:
        key = str(c).lower()
        if key in seen:
            continue
        seen.add(key)
        if c.is_dir():
            return c, warnings
    # Ninguno existe: devolvemos el nativo para crearlo, avisando.
    fallback = home / ".local" / "share" / "Colossal Order" / "Cities_Skylines"
    # Si hay instalacion Heroic pero sin user_dir, preferir el prefijo esperado.
    heroic_pref = home / "Games" / "Heroic" / "Prefixes" / "pfx" / "drive_c" / "users" / "steamuser" / "AppData" / "Local" / "Colossal Order" / "Cities_Skylines"
    if "Heroic" in str(install_dir) and not fallback.is_dir():
        warnings.append(
            f"No se encontro el perfil del juego; se usara {heroic_pref}. "
            "Arranca el juego una vez para que cree la carpeta."
        )
        return heroic_pref, warnings
    return fallback, warnings


def detect_game(override: str | None = None) -> GameInstall | None:
    """Encuentra la instalacion de Cities: Skylines y sus rutas de contenido.

    ``<instalacion>/Files`` es solo el contenido de fabrica (HardMode,
    UnlimitedMoney...). Los mods de usuario van en el perfil del jugador
    (``Addons/Mods``, ``Addons/Assets``...): lo confirma el propio
    ``output_log.txt``, que carga ``userGameState.cgs`` desde
    ``C:\\users\\...\\AppData\\Local\\Colossal Order\\Cities_Skylines``.
    """
    settings = load_settings()
    if override:
        settings["game_dir"] = override

    candidates: list[tuple[Path, str]] = []
    if settings.get("game_dir"):
        candidates.append((Path(settings["game_dir"]).expanduser(), "config"))
    candidates.extend((d, "auto") for d in _candidate_dirs())

    for d, source in candidates:
        if not d.is_dir() or not _looks_like_install(d):
            continue

        content = d / CONTENT_ROOT_NAME
        warnings: list[str] = []
        if not content.is_dir():
            # Algunas instalaciones antiguas usan la raiz directo.
            if (d / "Maps").is_dir() or (d / "Mods").is_dir():
                content = d
                warnings.append(
                    "No se encontro el directorio 'Files'; se usara la raiz de la "
                    "instalacion. Verifica que los mods terminen en Mods/ y Addons/."
                )
            else:
                continue

        launcher_settings = _read_json(d / "launcher-settings.json")
        version = str(launcher_settings.get("version") or "")
        app_id = str(launcher_settings.get("gameId") or "")
        launcher = str(launcher_settings.get("distPlatform") or "")

        if launcher_settings.get("steamWorkshopDisabled"):
            warnings.append(
                "El launcher tiene 'steamWorkshopDisabled': por eso hay que instalar "
                "los mods a mano. CS1 Mods Installer se encarga de eso."
            )
        if not version:
            warnings.append("No se pudo leer la version del juego de launcher-settings.json.")

        user_dir, user_warnings = _find_user_dir(d)
        warnings.extend(user_warnings)

        return GameInstall(
            install_dir=d,
            content_root=content,
            user_dir=user_dir,
            version=version,
            app_id=app_id,
            launcher=launcher,
            source=source,
            warnings=warnings,
        )
    return None


def require_game(override: str | None = None) -> GameInstall:
    g = detect_game(override)
    if g is None:
        raise FileNotFoundError(
            "No se encontro Cities: Skylines. Indica la carpeta con "
            "  cs1-mods-installer --game-dir /ruta/a/CitiesSkylines"
        )
    return g
