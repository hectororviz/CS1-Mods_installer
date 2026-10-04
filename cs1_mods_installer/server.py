"""Servidor local de CS1 Mods Installer.

Escucha solo en 127.0.0.1 (nunca en la red) y sirve la interfaz web junto a una
API JSON pequeña. El cliente abre el navegador contra este servidor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import catalog, images, index, installer, smods, steam
from .config import GameInstall, detect_game, disabled_root, manifest_path
from .jobs import REGISTRY

WEB_DIR = Path(__file__).parent / "web"

app = FastAPI(title="CS1 Mods Installer", docs_url=None, redoc_url=None)

_game: GameInstall | None = None


def game() -> GameInstall | None:
    global _game
    if _game is None:
        _game = detect_game()
    return _game


def require_game() -> GameInstall:
    g = game()
    if g is None:
        raise HTTPException(
            503,
            "No se encontro Cities: Skylines. Indica la carpeta con "
            "--game-dir /ruta/a/CitiesSkylines",
        )
    return g


# --------------------------------------------------------------------------
# Modelos
# --------------------------------------------------------------------------


class InstallReq(BaseModel):
    url: str = Field(..., description="URL de la ficha en smods.ru")


class FolderReq(BaseModel):
    folder: str
    path: str = ""


class ToggleReq(BaseModel):
    folder: str
    path: str
    enabled: bool


class IndexReq(BaseModel):
    pages: int = Field(100, ge=1, le=2000)


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


@app.get("/api/state")
def api_state() -> dict[str, Any]:
    g = game()
    idx = index.load()
    installed = installer.list_installed(g) if g else []
    return {
        "game": g.to_dict() if g else None,
        "index": {
            "entries": len(idx),
            "pages": idx.pages,
            "built_at": idx.built_at,
            "complete": idx.complete,
        },
        "installed": [i.to_dict() for i in installed],
        "counts": {
            "installed": len(installed),
            "enabled": sum(1 for i in installed if i.enabled),
            "managed": sum(1 for i in installed if i.managed),
        },
        "paths": {
            "manifest": str(manifest_path()),
            "disabled": str(disabled_root()),
        },
        "jobs": [j.to_dict() for j in REGISTRY.recent(10)],
    }


@app.get("/api/browse")
def api_browse(page: int = Query(1, ge=1)) -> dict[str, Any]:
    try:
        cards = catalog.browse(page, game())
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"No se pudo leer smods.ru: {e}") from e
    return {"page": page, "cards": [c.to_dict() for c in cards]}


@app.get("/api/search")
def api_search(q: str = Query(..., min_length=1), limit: int = 40) -> dict[str, Any]:
    idx = index.load()
    if not len(idx):
        raise HTTPException(
            409,
            "El indice esta vacio. Genera uno primero (pestana 'Indice').",
        )
    try:
        cards = catalog.search(q, game(), limit=limit)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Busqueda fallida: {e}") from e
    return {"query": q, "cards": [c.to_dict() for c in cards], "searched": len(idx)}


@app.get("/api/mod")
def api_mod(url: str = Query(...)) -> dict[str, Any]:
    try:
        return catalog.detail(url, game())
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"No se pudo leer la ficha: {e}") from e


@app.post("/api/enrich")
def api_enrich(req: dict[str, Any] | None = None) -> dict[str, Any]:
    urls = []
    if isinstance(req, dict):
        urls = req.get("urls") or []
    if not isinstance(urls, list):
        urls = []
    try:
        cards = catalog.enrich_batch(urls, game())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"No se pudo enriquecer: {e}") from e
    return {"cards": [c.to_dict() for c in cards]}


@app.get("/api/installed")
def api_installed() -> dict[str, Any]:
    g = require_game()
    return {"installed": [i.to_dict() for i in installer.list_installed(g)]}


@app.post("/api/install")
def api_install(req: InstallReq) -> dict[str, Any]:
    g = require_game()
    job = REGISTRY.create("install", req.url)
    REGISTRY.run(job, lambda j: catalog.install_job(j, req.url, g))
    return {"job": job.to_dict()}


@app.post("/api/remove")
def api_remove(req: FolderReq) -> dict[str, Any]:
    require_game()
    path = Path(req.path or (installer.load_manifest().get("mods", {})
                             .get(req.folder.lower(), {}).get("path", "")))
    if not path.is_absolute() or not path.exists():
        raise HTTPException(404, f"No encuentro la carpeta {req.folder}")
    try:
        removed = installer.uninstall(path)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"removed": removed, "folder": req.folder}


@app.post("/api/toggle")
def api_toggle(req: ToggleReq) -> dict[str, Any]:
    require_game()
    path = Path(req.path)
    if not path.is_absolute():
        raise HTTPException(400, "Ruta invalida")
    try:
        moved = installer.set_enabled(path, req.enabled)
    except OSError as e:
        raise HTTPException(500, f"No se pudo mover la carpeta: {e}") from e
    return {"moved": moved, "folder": req.folder, "enabled": req.enabled}


@app.post("/api/index")
def api_index(req: IndexReq) -> dict[str, Any]:
    job = REGISTRY.create("index", f"{req.pages} paginas")
    REGISTRY.run(job, lambda j: catalog.index_job(j, req.pages))
    return {"job": job.to_dict()}


@app.get("/api/job/{job_id}")
def api_job(job_id: str) -> dict[str, Any]:
    job = REGISTRY.get(job_id)
    if not job:
        raise HTTPException(404, "Tarea no encontrada")
    return job.to_dict()


@app.get("/api/image/{workshop_id}")
def api_image(workshop_id: str) -> Any:
    """Caratula del mod, descargada y reescalada bajo demanda."""
    if not workshop_id.isdigit():
        raise HTTPException(400, "id invalido")
    cached = images.cache_file(workshop_id)
    if cached.is_file():
        return FileResponse(cached, media_type="image/webp")

    info = steam.fetch([workshop_id]).get(workshop_id)
    if not info or not info.preview_url:
        raise HTTPException(404, "Sin caratula")
    path = images.get(workshop_id, info.preview_url)
    if not path:
        raise HTTPException(502, "No se pudo descargar la caratula")
    return FileResponse(path, media_type="image/webp")


@app.get("/api/robots")
def api_robots() -> dict[str, Any]:
    """Que rutas permite smods.ru, para poder explicarlo en la UI."""
    client = smods.make_client()
    try:
        smods.ROBOTS.load(client)
        return {
            "loaded": smods.ROBOTS.loaded,
            "disallowed": [p for p, dis in smods.ROBOTS.rules if dis],
            "allowed": [p for p, dis in smods.ROBOTS.rules if not dis],
        }
    finally:
        client.close()


# --------------------------------------------------------------------------
# Interfaz
# --------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def root() -> Any:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
