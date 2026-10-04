"""Instalacion, listado y desinstalacion de mods.

Decisiones que importan:

* **Clasificamos por el contenido del .zip, no por el tag de Steam.** Si hay un
  ``.dll`` es un mod de codigo y va a ``Files/Mods/``; si hay un ``.crp`` es un
  asset y va a ``Files/Addons/Assets/``. El tag solo sirve de aviso previo.
* **Nunca escribimos dentro del zip.** Se extrae a un temporal y se mueve al
  destino, asi una descarga corrupta no deja el juego con medio mod.
* **Path traversal**: se rechazan rutas absolutas, ``..`` y symlinks antes de
  escribir nada.
* **No tocamos el estado del launcher.** La lista de mods activados vive en
  ``userGameState.cgs``, un binario propietario; escribirlo a ciegas podria
  corromper la configuracion. Por eso "deshabilitar" es mover la carpeta.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import GameInstall, disabled_root, ensure_dirs, manifest_path

# Techo defensivo contra zip bombs: ningun mod de CS pasa de esto.
MAX_UNCOMPRESSED = 4 * 1024**3  # 4 GiB
MAX_RATIO = 400

# Valores posibles de ArchiveInfo.kind, decidedos mirando el contenido del zip.
# "style" solo existe aqui: el Workshop no tiene tag de estilo, asi que un
# .style.xml se descubre al extraerlo.
KINDS = ("unknown", "mod", "asset", "style", "theme", "map", "scenario")

RE_UNSAFE = re.compile(r"[\x00-\x1f<>:\"|?*\\/]")
RE_WORKSHOP_PREFIX = re.compile(r"^(\d{5,12})\s+(.*)$")


@dataclass
class ArchiveInfo:
    total_files: int = 0
    total_size: int = 0
    top_dirs: list[str] = field(default_factory=list)
    has_dll: bool = False
    has_crp: bool = False
    has_style_xml: bool = False
    has_map: bool = False
    has_scenario: bool = False
    kind: str = "unknown"


@dataclass
class Installed:
    folder: str
    path: str
    kind: str = "unknown"
    title: str = ""
    workshop_id: str = ""
    size: int = 0
    enabled: bool = True
    managed: bool = False  # instalado por CS1 Mods Installer (esta en el manifiesto)
    source: str = ""  # "juego" o "cs1-mods"
    installed_at: str = ""
    smods_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class UnsafeArchive(ValueError):
    pass


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------


def safe_name(name: str, fallback: str = "mod") -> str:
    """Nombre de carpeta utilizable en el sistema de ficheros.

    Quita separadores y caracteres de control, y colapsa las rachas de puntos
    (``a/../../b`` deja de ser ``a....b`` y pasa a ``a.b``). Los puntos
    simples se respetan, asi que ``1.21.1-f9`` sobrevive intacto.
    """
    name = RE_UNSAFE.sub("", name).strip()
    name = re.sub(r"\.{2,}", ".", name).strip(".")
    name = re.sub(r"\s+", " ", name)
    if not name:
        name = fallback
    return name[:120]


def dir_size(path: Path) -> int:
    total = 0
    for p in Path(path).rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def sha256(path: Path, limit: int = 0) -> str:
    h = hashlib.sha256()
    read = 0
    with open(path, "rb") as fh:
        while chunk := fh.read(1024 * 1024):
            h.update(chunk)
            read += len(chunk)
            if limit and read >= limit:
                break
    return h.hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Analisis del zip
# --------------------------------------------------------------------------


def inspect_zip(path: Path) -> ArchiveInfo:
    """Mira el contenido del zip y decide a donde va."""
    info = ArchiveInfo()
    tops: list[str] = []
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        info.total_files = len(infos)
        for zi in infos:
            name = zi.filename
            if zi.is_dir():
                continue
            parts = Path(name).parts
            if parts:
                top = parts[0]
                if top not in tops:
                    tops.append(top)
            low = name.lower()
            if low.endswith(".dll"):
                info.has_dll = True
            elif low.endswith(".crp"):
                info.has_crp = True
            elif low.endswith((".style.xml", ".themestyle.xml")):
                info.has_style_xml = True
            elif low.endswith((".crp", ".png", ".jpg")) and "/maps/" in low.replace("\\", "/"):
                info.has_map = True
            if "/scenarios/" in low.replace("\\", "/") or low.endswith(".scenario.xml"):
                info.has_scenario = True
            info.total_size += zi.file_size
    info.top_dirs = tops[:5]

    # el orden importa: un mod de codigo con assets sigue siendo mod
    if info.has_dll:
        info.kind = "mod"
    elif info.has_style_xml:
        info.kind = "style"
    elif info.has_crp:
        info.kind = "asset"
    elif info.has_scenario:
        info.kind = "scenario"
    elif info.has_map:
        info.kind = "map"
    return info


def _check_entry(name: str) -> None:
    """Valida un nombre de entrada del zip antes de extraerlo."""
    if not name:
        raise UnsafeArchive("Entrada sin nombre en el zip.")
    if name.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", name):
        raise UnsafeArchive(f"Ruta absoluta no permitida en el zip: {name!r}")
    normalized = name.replace("\\", "/")
    if ".." in Path(normalized).parts:
        raise UnsafeArchive(f"Path traversal bloqueado: {name!r}")


def safe_extract(zip_path: Path, dest: Path) -> int:
    """Extrae rejecting rutas peligrosas. Devuelve el nº de ficheros."""
    dest.mkdir(parents=True, exist_ok=True)
    written = 0
    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()
        total = sum(i.file_size for i in infos)
        if total > MAX_UNCOMPRESSED:
            raise UnsafeArchive(
                f"El zip descomprime a {total / 1024**3:.1f} GiB, por encima del "
                f"limite de {MAX_UNCOMPRESSED / 1024**3:.0f} GiB. Sospechoso."
            )
        for zi in infos:
            _check_entry(zi.filename)
            # symlinks: el bit externo 0xA000 marca un enlace simbolico
            if (zi.external_attr >> 16) & 0o170000 == 0o120000:
                raise UnsafeArchive(f"Symlink bloqueado en el zip: {zi.filename!r}")
            target = dest / zi.filename
            # doble comprobacion: el destino debe seguir dentro de dest
            try:
                target.resolve().relative_to(dest.resolve())
            except ValueError:
                raise UnsafeArchive(f"Entrada fuera del destino: {zi.filename!r}") from None
            if zi.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(zi) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out, length=1024 * 1024)
            written += 1
    return written


def strip_single_root(src: Path) -> Path:
    """Si el zip envuelve todo en una unica carpeta, la desarrolla.

    ``3810565217 Quay Tools/QuayTools.dll`` y ``QuayTools.dll`` son el mismo
    mod; el juego espera la segunda forma dentro de ``Files/Mods/``.
    """
    entries = [p for p in src.iterdir() if p.name != "__MACOSX"]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return src


# --------------------------------------------------------------------------
# Destinos
# --------------------------------------------------------------------------


def dest_dir_for(game: GameInstall, kind: str) -> Path:
    return {
        "mod": game.mods_dir,
        "asset": game.assets_dir,
        "style": game.styles_dir,
        "theme": game.map_themes_dir,
        "map": game.maps_dir,
        "scenario": game.scenarios_dir,
    }.get(kind, game.mods_dir)


def _target_folder(zip_path: Path, info: ArchiveInfo, title: str, workshop_id: str) -> str:
    """Nombre de la carpeta destino.

    Los zips de smods vienen como ``<workshopID> <Nombre>/...``. Mantener el
    prefijo del workshop id es lo que nos permite volver a trazar un mod
    instalado hasta su origen.
    """
    candidate = ""
    if info.top_dirs:
        candidate = info.top_dirs[0]
    if workshop_id and not candidate.startswith(workshop_id):
        base = safe_name(candidate or title or zip_path.stem, fallback="mod")
        return f"{workshop_id} {base}"[:140]
    return safe_name(candidate or title or zip_path.stem, fallback="mod")


# --------------------------------------------------------------------------
# Manifiesto
# --------------------------------------------------------------------------


def load_manifest() -> dict[str, Any]:
    p = manifest_path()
    if p.is_file():
        try:
            return json.loads(p.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_manifest(data: dict[str, Any]) -> None:
    ensure_dirs()
    tmp = manifest_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
    tmp.replace(manifest_path())


def _manifest_key(folder: str) -> str:
    return folder.lower()


def record_install(record: dict[str, Any]) -> None:
    m = load_manifest()
    m.setdefault("mods", {})[_manifest_key(record["folder"])] = record
    save_manifest(m)


def forget(folder: str) -> None:
    m = load_manifest()
    m.get("mods", {}).pop(_manifest_key(folder), None)
    save_manifest(m)


# --------------------------------------------------------------------------
# Instalar / desinstalar
# --------------------------------------------------------------------------


def install(
    zip_path: Path,
    game: GameInstall,
    *,
    title: str = "",
    workshop_id: str = "",
    smods_url: str = "",
    expected_kind: str = "unknown",
    overwrite: bool = True,
) -> Installed:
    """Instala un .zip ya descargado en la ruta que le corresponde."""
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise FileNotFoundError(zip_path)

    info = inspect_zip(zip_path)
    if info.kind == "unknown":
        raise ValueError(
            "No se reconoce el contenido del zip: no hay ni DLL ni CRP. "
            "Puede ser un mapa o un formato no soportado."
        )
    if expected_kind not in ("unknown", info.kind):
        # el tag de Steam y el contenido no coinciden: gana el contenido, pero
        # avisamos al usuario en la UI
        pass

    kind = info.kind
    dest_root = dest_dir_for(game, kind)
    folder = _target_folder(zip_path, info, title, workshop_id)
    final = dest_root / folder

    with tempfile.TemporaryDirectory(prefix="cs1mods-", dir=str(_tmp_base())) as tmpdir:
        tmp = Path(tmpdir) / "extract"
        safe_extract(zip_path, tmp)
        root = strip_single_root(tmp)

        dest_root.mkdir(parents=True, exist_ok=True)
        backup: Path | None = None
        if final.exists():
            if not overwrite:
                raise FileExistsError(
                    f"Ya existe {final}. Usa 'sobrescribir' o desinstalalo antes."
                )
            backup = dest_root / f".cs1mods-backup-{folder}"
            if backup.exists():
                shutil.rmtree(backup)
            final.rename(backup)
        try:
            root.replace(final)
        except OSError:
            # root y final pueden estar en filesystems distintos: copiamos
            shutil.copytree(root, final)
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)

    rec = {
        "folder": folder,
        "path": str(final),
        "kind": kind,
        "title": title or folder,
        "workshop_id": workshop_id,
        "size": dir_size(final),
        "enabled": True,
        "installed_at": now_iso(),
        "smods_url": smods_url,
        "sha256": sha256(zip_path, limit=64 * 1024 * 1024),
    }
    record_install(rec)
    return Installed(
        folder=rec["folder"],
        path=rec["path"],
        kind=rec["kind"],
        title=rec["title"],
        workshop_id=rec["workshop_id"],
        size=rec["size"],
        enabled=True,
        managed=True,
        source="cs1-mods",
        installed_at=rec["installed_at"],
        smods_url=rec["smods_url"],
    )


def _tmp_base() -> Path:
    base = Path(os.environ.get("TMPDIR") or "/tmp")
    base.mkdir(parents=True, exist_ok=True)
    return base


def uninstall(folder_path: Path, purge: bool = True) -> bool:
    """Borra un mod instalado. Devuelve si habia algo que borrar."""
    folder_path = Path(folder_path)
    if not folder_path.exists():
        return False
    # salvaguarda: solo dentro de las carpetas de contenido del juego
    if folder_path.parent.name not in {
        "Mods",
        "Assets",
        "Styles",
        "MapThemes",
        "Maps",
        "Scenarios",
    }:
        raise ValueError(
            f"Por seguridad no borro {folder_path}: no esta dentro de una "
            "carpeta de contenido del juego."
        )
    if purge:
        shutil.rmtree(folder_path)
        forget(folder_path.name)
    return True


def _move(src: Path, dest: Path) -> None:
    """Mueve esperando que src y dest compartan filesystem.

    ``Path.replace`` usa ``os.replace``, que falla con EXDEV si el juego esta
    en otro disco que el estado de la aplicacion. En ese caso copiamos y borramos.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.replace(dest)
    except OSError:
        shutil.move(str(src), str(dest))


def set_enabled(folder_path: Path, enabled: bool) -> bool:
    """Habilita/deshabilita moviendo la carpeta (no toca binarios del launcher)."""
    folder_path = Path(folder_path)
    if enabled:
        store = disabled_root() / folder_path.name
        if not folder_path.exists() and store.exists():
            _move(store, folder_path)
            return True
        return False

    if not folder_path.exists():
        return False
    ensure_dirs()
    store_root = disabled_root()
    store_root.mkdir(parents=True, exist_ok=True)
    dest = store_root / folder_path.name
    if dest.exists():
        shutil.rmtree(dest)
    _move(folder_path, dest)
    return True


# --------------------------------------------------------------------------
# Listado
# --------------------------------------------------------------------------

SCAN_DIRS = (
    ("Mods", "mod"),
    ("Addons/Assets", "asset"),
    ("Addons/Styles", "style"),
    ("Addons/MapThemes", "theme"),
    ("Maps", "map"),
    ("Scenarios", "scenario"),
)


def list_installed(game: GameInstall) -> list[Installed]:
    """Todos los mods presentes en el juego, gestionados o no."""
    manifest = load_manifest().get("mods", {})
    out: list[Installed] = []
    seen: set[str] = set()

    scan_roots: list[tuple[Path, str]] = [
        (game.mods_dir, "mod"),
        (game.assets_dir, "asset"),
        (game.styles_dir, "style"),
        (game.map_themes_dir, "theme"),
        (game.maps_dir, "map"),
        (game.scenarios_dir, "scenario"),
    ]
    for root, kind in scan_roots:
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            rec = manifest.get(_manifest_key(entry.name), {})
            m = RE_WORKSHOP_PREFIX.match(entry.name)
            out.append(
                Installed(
                    folder=entry.name,
                    path=str(entry),
                    kind=rec.get("kind") or kind,
                    title=rec.get("title") or (m.group(2) if m else entry.name),
                    workshop_id=rec.get("workshop_id") or (m.group(1) if m else ""),
                    size=rec.get("size") or dir_size(entry),
                    enabled=True,
                    managed=bool(rec),
                    source="cs1-mods" if rec else "juego",
                    installed_at=rec.get("installed_at", ""),
                    smods_url=rec.get("smods_url", ""),
                )
            )
            seen.add(_manifest_key(entry.name))

    # mods deshabilitados (estan fuera del arbol del juego)
    store = disabled_root()
    if store.is_dir():
        for entry in sorted(store.iterdir()):
            if not entry.is_dir():
                continue
            rec = manifest.get(_manifest_key(entry.name), {})
            m = RE_WORKSHOP_PREFIX.match(entry.name)
            out.append(
                Installed(
                    folder=entry.name,
                    path=str(entry),
                    kind=rec.get("kind") or "mod",
                    title=rec.get("title") or (m.group(2) if m else entry.name),
                    workshop_id=rec.get("workshop_id") or (m.group(1) if m else ""),
                    size=rec.get("size") or dir_size(entry),
                    enabled=False,
                    managed=bool(rec),
                    source="cs1-mods" if rec else "juego",
                    installed_at=rec.get("installed_at", ""),
                    smods_url=rec.get("smods_url", ""),
                )
            )
            seen.add(_manifest_key(entry.name))

    return out


def is_installed(workshop_id: str, game: GameInstall) -> Installed | None:
    """Busca un workshop id entre lo instalado (incluido deshabilitado)."""
    if not workshop_id:
        return None
    for inst in list_installed(game):
        if inst.workshop_id == workshop_id:
            return inst
    return None
