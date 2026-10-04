"""Capa que une smods + Steam + instalador.

Aqui viven las decisiones de producto: que se muestra en una tarjeta, que avisa
al usuario y como se decide el destino de un mod.
"""

from __future__ import annotations

import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import images, index, installer, modsbase, smods, steam
from .config import GameInstall
from .jobs import Job

# Cache de fichas en memoria: abrir la pagina 1 y volver a ella no debe
# volver a pedir 10 HTML a smods.
_detail_cache: dict[str, smods.ModDetail] = {}
_detail_lock = threading.Lock()

# Cache de las paginas de listado, con caducidad.
_page_cache: dict[int, tuple[float, list[dict[str, str]]]] = {}
_page_lock = threading.Lock()
PAGE_TTL = 300.0

# Cuantas fichas se leen a la vez. 6 threads bajan la pagina de ~50 s a ~10 s
# sin parecer un escaner.
DETAIL_WORKERS = 6

# Compatibilidad: si el tag dice f5 y el juego es f9, avisamos pero no
# bloqueamos. Muchos mods funcionan igual y el usuario decide.
STRICT_COMPAT = False


@dataclass
class Card:
    url: str
    title: str
    kind: str = "unknown"
    workshop_id: str = ""
    size: int = 0
    size_text: str = ""
    author: str = ""
    revision: str = ""
    preview_url: str = ""
    compat: str = ""
    compat_status: str = "unknown"
    tags: list[str] | None = None
    installed: bool = False
    enabled: bool = True
    managed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def get_detail(url: str, client: smods.httpx.Client | None = None) -> smods.ModDetail:
    with _detail_lock:
        hit = _detail_cache.get(url)
    if hit:
        return hit
    d = smods.mod_detail(url, client)
    with _detail_lock:
        _detail_cache[url] = d
    return d


def fetch_details(
    urls: list[str], workers: int = DETAIL_WORKERS
) -> dict[str, smods.ModDetail]:
    """Descarga muchas fichas en paralelo y devuelve las que si se pudieron.

    En serie son ~5 s por ficha, o sea ~50 s para una pagina de 10; con 6
    hilos baja a ~10 s. El pool es pequeño a proposito: queremos ser rapidos
    sin martillear smods.ru.

    Devuelve un dict url -> ficha. Las que fallaron simplemente no aparecen:
    antes se emparejaban por posicion con ``zip`` y una ficha rota hacia que el
    titulo de un mod acabara junto al enlace de otro.
    """
    out: dict[str, smods.ModDetail] = {}
    pending: list[str] = []
    with _detail_lock:
        for u in urls:
            hit = _detail_cache.get(u)
            if hit is not None:
                out[u] = hit
            else:
                pending.append(u)

    if not pending:
        return out

    client = smods.make_client(timeout=25.0)
    try:
        if not smods.ROBOTS.loaded:
            smods.ROBOTS.load(client)

        def one(url: str) -> tuple[str, smods.ModDetail | None]:
            try:
                return url, get_detail(url, client)
            except Exception:
                return url, None  # ficha rota: no tumba la pagina entera

        with ThreadPoolExecutor(max_workers=min(workers, len(pending))) as pool:
            for url, detail in pool.map(one, pending):
                if detail is not None:
                    out[url] = detail
    finally:
        client.close()
    return out


def enrich(
    entries: list[dict[str, str]], game: GameInstall | None
) -> list[Card]:
    """Convierte entradas del indice en tarjetas con metadata de Steam."""
    if not entries:
        return []

    details = fetch_details([e["url"] for e in entries])
    ids = [d.workshop_id for d in details.values() if d.workshop_id]
    meta = steam.fetch(ids) if ids else {}

    installed_map: dict[str, installer.Installed] = {}
    if game:
        for i in installer.list_installed(game):
            if i.workshop_id:
                installed_map[i.workshop_id] = i

    cards: list[Card] = []
    for e in entries:
        d = details.get(e["url"])
        if d is None:
            continue
        info = meta.get(d.workshop_id)
        inst = installed_map.get(d.workshop_id)
        kind = info.kind if info and info.kind != "unknown" else "unknown"
        cards.append(
            Card(
                url=e["url"],
                title=d.title or e.get("title", ""),
                kind=kind,
                workshop_id=d.workshop_id,
                size=info.file_size if info else 0,
                size_text=d.size_text,
                author=d.author,
                revision=d.revision,
                preview_url=info.preview_url if info else "",
                compat=info.compat if info else "",
                compat_status=steam.compat_status(info, game.version if game else ""),
                tags=info.tags if info else [],
                installed=inst is not None,
                enabled=inst.enabled if inst else True,
                managed=inst.managed if inst else False,
            )
        )
    return cards


def catalog_entries(page: int = 1) -> list[dict[str, str]]:
    """Entradas del listado, cacheadas en memoria un rato."""
    with _page_lock:
        hit = _page_cache.get(page)
        if hit and time.time() - hit[0] < PAGE_TTL:
            return hit[1]

    entries = [e.__dict__ for e in smods.catalog_page(page)]
    with _page_lock:
        _page_cache[page] = (time.time(), entries)
        if len(_page_cache) > 64:  # no crecer sin limite
            for old in sorted(_page_cache, key=lambda k: _page_cache[k][0])[:32]:
                _page_cache.pop(old, None)
    return entries


def browse(page: int = 1, game: GameInstall | None = None) -> list[Card]:
    return enrich(catalog_entries(page), game)


def search(
    query: str, game: GameInstall | None = None, limit: int = 40
) -> list[Card]:
    idx = index.load()
    hits = index.search(idx, query, limit=limit)
    return enrich(hits, game)


def detail(url: str, game: GameInstall | None = None) -> dict[str, Any]:
    d = get_detail(url)
    info = steam.fetch([d.workshop_id]).get(d.workshop_id) if d.workshop_id else None
    inst = (
        installer.is_installed(d.workshop_id, game)
        if (game and d.workshop_id)
        else None
    )
    return {
        "url": d.page_url,
        "title": d.title,
        "author": d.author,
        "author_id": d.author_id,
        "workshop_id": d.workshop_id,
        "size_text": d.size_text,
        "size": info.file_size if info else 0,
        "revision": d.revision,
        "description": d.description,
        "description_steam": (info.description if info else ""),
        "preview_url": info.preview_url if info else "",
        "tags": info.tags if info else [],
        "kind": (info.kind if info else "unknown"),
        "compat": info.compat if info else "",
        "compat_status": steam.compat_status(info, game.version if game else ""),
        "game_version": game.version if game else "",
        "installed": inst.to_dict() if inst else None,
    }


def install_job(job: Job, url: str, game: GameInstall) -> None:
    """Cuerpo del job de instalacion, con progreso en 4 pasos."""

    def step(pct: float, msg: str) -> None:
        job.progress = pct
        job.step = msg

    step(0.05, "Leyendo la ficha del mod...")
    d = get_detail(url)
    if not d.download_url:
        raise LookupError("Esta ficha no tiene enlace de descarga.")

    meta = steam.fetch([d.workshop_id]).get(d.workshop_id) if d.workshop_id else None
    expected = meta.kind if meta else "unknown"

    if game.version and meta and meta.compat and meta.compat != game.version:
        job.detail["compat_warning"] = (
            f"El mod esta etiquetado para {meta.compat} y tu juego es {game.version}. "
            "Puede funcionar o no; instalanlo si te animas."
        )
    if meta and meta.file_size and d.size_text:
        job.detail["size_note"] = (
            f"smods indica {d.size_text}; Steam indica "
            f"{steam.human_size(meta.file_size)}. Si difieren mucho, el mirror "
            "puede estar desactualizado."
        )

    step(0.15, "Preparando la descarga...")
    with tempfile.TemporaryDirectory(prefix="cs1mods-dl-") as tmp:
        archive = Path(tmp) / (d.download_name or f"{d.workshop_id or 'mod'}.zip")

        def on_progress(written: int, total: int | None) -> None:
            if total:
                frac = written / total
                step(0.2 + frac * 0.55, f"Descargando {steam.human_size(written)} de {steam.human_size(total)}")
            else:
                step(0.4, f"Descargando {steam.human_size(written)}")

        modsbase.download(d.download_url, archive, progress=on_progress)

        step(0.8, "Analizando el contenido...")
        info = installer.inspect_zip(archive)
        if info.kind == "unknown":
            raise ValueError(
                "El zip no contiene ni DLL ni CRP: no parece un mod de Cities: Skylines."
            )
        if expected != "unknown" and expected != info.kind:
            job.detail["kind_mismatch"] = (
                f"Steam lo clasifica como '{expected}' pero el archivo contiene "
                f"'{info.kind}'. Se instala como '{info.kind}', que es lo que el juego lee."
            )

        step(0.88, f"Instalando en {installer.dest_dir_for(game, info.kind).name}/...")
        rec = installer.install(
            archive,
            game,
            title=d.title,
            workshop_id=d.workshop_id,
            smods_url=d.page_url,
            expected_kind=expected,
        )
        job.detail["installed"] = rec.to_dict()

    # pre-calentamos la caratula: la primera carga de la UI ya la tiene
    if meta and meta.preview_url:
        try:
            images.get(meta.workshop_id, meta.preview_url)
        except Exception:
            pass

    step(1.0, "Listo.")
    time.sleep(0.2)


def index_job(job: Job, pages: int) -> None:
    def cb(p: int, msg: str) -> None:
        job.step = f"Leyendo {msg}"
        job.detail["page"] = p

    idx = index.build(pages=pages, progress=cb)
    job.detail["entries"] = len(idx)
    job.detail["pages"] = idx.pages
    job.progress = 1.0
    job.step = f"Indice con {len(idx)} mods"
