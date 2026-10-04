"""Cache de caratulas de los mods.

La imagen viene de ``preview_url`` de la API de Steam: es anonima y llega como
un PNG de **1000x1000 (~770 KB)**. Bajar eso para cada mod que se ve seria un
desastre, asi que:

* se descarga **bajo demanda** (cuando el navegador pide la imagen);
* se reescala con Pillow a un thumbnail y se guarda en disco;
* la siguientes visita se sirve desde el cache local, sin red.

Esto es lo que permite que la interfaz muestre caratulas sin depender de que el
terminal entienda imagenes: en la web es un ``<img>`` de losuyo.
"""

from __future__ import annotations

import io
import threading
from pathlib import Path

import httpx
from PIL import Image

from .config import USER_AGENT, image_cache_dir

THUMB_SIZE = (420, 420)
QUALITY = 82

# el prefijo de los ficheros ya cacheados, por ejemplo "3810565217.webp"
_SUFFIX = ".webp"

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def cache_file(workshop_id: str) -> Path:
    safe = "".join(c for c in workshop_id if c.isalnum())
    return image_cache_dir() / f"{safe}{_SUFFIX}"


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def get(workshop_id: str, preview_url: str, timeout: float = 25.0) -> Path | None:
    """Devuelve la ruta del thumbnail, descargandolo si hace falta."""
    if not workshop_id or not preview_url:
        return None

    dest = cache_file(workshop_id)
    if dest.is_file() and dest.stat().st_size > 0:
        return dest

    with _lock_for(workshop_id):
        # otro hilo pudo terminar mientras esperabamos el lock
        if dest.is_file() and dest.stat().st_size > 0:
            return dest
        try:
            with httpx.Client(
                timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}
            ) as client:
                r = client.get(preview_url)
                r.raise_for_status()
                raw = r.content
        except (httpx.HTTPError, OSError):
            return None

        try:
            with Image.open(io.BytesIO(raw)) as im:
                im.load()
                im = im.convert("RGB")
                # recorte cuadrado centrado antes de reescalar: las caratulas
                # del workshop suelen venir en 1:1, pero no siempre
                w, h = im.size
                side = min(w, h)
                left, top = (w - side) // 2, (h - side) // 2
                if (w, h) != (side, side):
                    im = im.crop((left, top, left + side, top + side))
                im = im.resize(THUMB_SIZE, Image.LANCZOS)
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(".tmp.webp")
                im.save(tmp, "WEBP", quality=QUALITY, method=4)
                tmp.replace(dest)
        except (OSError, ValueError):
            return None
        return dest


def cached_ids() -> list[str]:
    d = image_cache_dir()
    if not d.is_dir():
        return []
    return [p.stem for p in d.glob(f"*{_SUFFIX}")]


def clear() -> int:
    d = image_cache_dir()
    n = 0
    if d.is_dir():
        for p in d.glob(f"*{_SUFFIX}"):
            p.unlink(missing_ok=True)
            n += 1
    return n
