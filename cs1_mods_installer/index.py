"""Indice local del catalogo.

El buscador de smods.ru es ``GET /?s=...`` y ``robots.txt`` lo prohibe
explicitamente. En vez de saltarnos esa regla, la aplicacion construye un indice
propio con las paginas de listado (``/page/N``), que si estan permitidas, y
busca contra el.

El indice es incremental y reanudable: se guarda cuantas paginas se han leido
y seguir se continua desde ahi.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from . import smods
from .config import index_path

ProgressCb = Callable[[int, str], None]

# ~89.000 posts en el sitio; 10 por pagina de listado
MAX_PAGES = 9000


@dataclass
class Index:
    entries: list[dict[str, str]]
    pages: int
    built_at: str
    complete: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": self.entries,
            "pages": self.pages,
            "built_at": self.built_at,
            "complete": self.complete,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Index":
        return cls(
            entries=list(d.get("entries", [])),
            pages=int(d.get("pages", 0)),
            built_at=str(d.get("built_at", "")),
            complete=bool(d.get("complete", False)),
        )

    def __len__(self) -> int:
        return len(self.entries)


def load() -> Index:
    p = index_path()
    if p.is_file():
        try:
            return Index.from_dict(json.loads(p.read_text("utf-8")))
        except (json.JSONDecodeError, OSError, ValueError):
            return Index([], 0, "")
    return Index([], 0, "")


def save(idx: Index) -> None:
    import os

    p = index_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # tmp único por proceso: dos builds a la vez no deben pisarse
    tmp = p.with_name(f"{p.name}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(idx.to_dict(), ensure_ascii=False), "utf-8")
    tmp.replace(p)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def search(idx: Index, query: str, limit: int = 60) -> list[dict[str, Any]]:
    """Busca por titulo. Primero coincidencias exactas, luego por palabras."""
    q = _norm(query)
    if not q:
        return []
    terms = q.split()

    scored: list[tuple[int, int, dict[str, str]]] = []
    for pos, e in enumerate(idx.entries):
        title = e.get("title", "")
        norm = _norm(title)
        if not norm:
            continue
        score = 0
        if norm == q:
            score = 1000
        elif norm.startswith(q):
            score = 800
        elif q in norm:
            score = 600
        else:
            hits = sum(1 for t in terms if t in norm)
            if hits == len(terms):
                score = 300 + hits * 10
            elif hits:
                score = hits * 40
        if score:
            # desempate: los titulos mas cortos suelen ser los mas relevantes
            scored.append((score, len(title), e))

    scored.sort(key=lambda t: (-t[0], t[1], t[2].get("title", "")))
    return [e for _, _, e in scored[:limit]]


def build(
    pages: int = 100,
    start: int = 1,
    progress: ProgressCb | None = None,
    resume: bool = True,
    workers: int = 4,
) -> Index:
    """Lee paginas de listado y guarda el indice. Se puede reanudar.

    Las paginas se piden en lotes de ``workers`` en paralelo (smods ya
    tolera ese nivel: el detalle de fichas usa 6 hilos) pero se guardan
    en orden, asi ``pages`` siempre marca hasta donde el indice esta
    completo y retomar sigue funcionando.
    """
    idx = load() if resume else Index([], 0, "")
    from_page = start if not resume else idx.pages + 1
    seen = {e["url"] for e in idx.entries}

    client = smods.make_client()
    if not smods.ROBOTS.loaded:
        smods.ROBOTS.load(client)

    def one(p: int) -> tuple[int, list | str]:
        last = "desconocido"
        for _ in range(3):
            try:
                return p, smods.catalog_page(p, client)
            except Exception as e:  # red, corte transitorio, cambio de maquetacion...
                last = f"{type(e).__name__}: {e}"
                time.sleep(5)
        return p, last

    added = 0
    end = min(from_page + pages, MAX_PAGES + 1)
    width = max(1, workers)
    try:
        with ThreadPoolExecutor(max_workers=width) as pool:
            p = from_page
            while p < end:
                batch = list(range(p, min(p + width, end)))
                got = dict(pool.map(one, batch))
                stop = False
                for bp in batch:
                    res = got[bp]
                    if isinstance(res, str):
                        if progress:
                            progress(bp, f"pagina {bp}: {res}, parando")
                        stop = True
                        break
                    if not res:
                        if progress:
                            progress(bp, "fin del catalogo")
                        idx.complete = True
                        stop = True
                        break
                    for e in res:
                        if e.url not in seen:
                            seen.add(e.url)
                            idx.entries.append({"url": e.url, "title": e.title})
                            added += 1
                    idx.pages = bp
                    idx.built_at = time.strftime("%Y-%m-%dT%H:%M:%S")
                save(idx)
                if progress:
                    progress(idx.pages, f"{len(idx.entries)} mods (+{added})")
                if stop:
                    break
                p = batch[-1] + 1
                smods.polite(0.35)  # cortesia entre lotes
    finally:
        client.close()

    save(idx)
    return idx
