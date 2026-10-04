"""Scraper de smods.ru: catalogo, detalle y enlaces de descarga.

CS1 Mods Installer solo pide rutas que robots.txt permite. El buscador del sitio (``/?s=``)
esta prohibido, asi que la busqueda de texto se resuelve contra un indice local
(ver :mod:`cs1_mods_installer.index`).
"""

from __future__ import annotations

import html
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .config import SMODS_BASE, USER_AGENT, MODSBASE_RE

# --- regex -----------------------------------------------------------------

RE_ARCHIVE_LINK = re.compile(r'href="(https://smods\.ru/archives/\d+)"[^>]*>\s*([^<]{2,120})<')
RE_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
RE_WORKSHOP_ID = re.compile(r"steamcommunity\.com/workshop/filedetails/\?id=(\d+)")
RE_STEAM_PROFILE = re.compile(r"steamcommunity\.com/profiles/(\d{17})")
# OJO: "skymods-excerpt-btn" y "skymods-sidebar" de mas abajo son clases CSS
# de smods.ru, no nuestras. Aunque esta aplicacion se llame CS1 Mods Installer,
# esos dos nombres no se renombran: son los que tiene la web.
RE_DOWNLOAD = re.compile(r'class="skymods-excerpt-btn"[^>]*href="([^"]+)"')
RE_MODSBASE_ANY = re.compile(r'href="(https://modsbase\.com/[^"]+)"')


def _field(label: str) -> re.Pattern[str]:
    """Los metadatos vienen como ``<strong>Label:</strong> <span|a>valor``."""
    return re.compile(
        rf"<strong>{label}:</strong>\s*(?:<a\b[^>]*>|<span\b[^>]*>)?\s*([^<]+)",
        re.I,
    )


RE_FIELD_SIZE = _field("File size")
RE_FIELD_AUTHOR = _field("Author")
RE_FIELD_REVISION = _field("Last revision")
RE_AUTHOR_URL = re.compile(
    r"<strong>Author:</strong>\s*<a\b[^>]*href=\"([^\"]+)\"", re.I
)

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(html_fragment: str) -> str:
    return html.unescape(_TAG_RE.sub("", html_fragment)).strip()


# --- robots ---------------------------------------------------------------


class Robots:
    """Parser minimo de robots.txt, cacheado en memoria."""

    def __init__(self) -> None:
        self.rules: list[tuple[str, bool]] = []
        self.loaded = False

    def load(self, client: httpx.Client) -> None:
        try:
            r = client.get(f"{SMODS_BASE}/robots.txt", timeout=20)
            r.raise_for_status()
            # el archivo viene con BOM, que romperia el primer "User-agent"
            text = r.text.lstrip("\ufeff")
            applies = False
            for raw in text.splitlines():
                line = raw.split("#", 1)[0].strip()
                if not line or ":" not in line:
                    continue
                field_name, _, value = line.partition(":")
                field_name = field_name.strip().lower()
                value = value.strip()
                if field_name == "user-agent":
                    applies = value == "*"
                elif applies and field_name in ("disallow", "allow"):
                    if value:
                        self.rules.append((value, field_name == "disallow"))
            self.loaded = True
        except (httpx.HTTPError, OSError):
            # Si no se puede leer, asumimos que no hay restricciones.
            self.loaded = True

    def allows(self, url: str) -> bool:
        path = urlparse(url).path or "/"
        if urlparse(url).query:
            path += "?" + urlparse(url).query
        best: tuple[int, bool] | None = None
        for pattern, disallowed in self.rules:
            if _robots_match(path, pattern):
                length = len(pattern)
                # la regla mas especifica gana; "allow" gana a igual longitud
                if best is None or length > best[0] or (length == best[0] and not disallowed):
                    best = (length, not disallowed)
        return True if best is None else best[1]


def _robots_match(path: str, pattern: str) -> bool:
    if pattern == "/":
        return path.startswith("/")
    if pattern.endswith("$"):
        return path.rstrip("/").endswith(pattern[:-1].rstrip("/"))
    return path.startswith(pattern)


ROBOTS = Robots()


# --- modelos ---------------------------------------------------------------


@dataclass
class CatalogEntry:
    url: str
    title: str


@dataclass
class ModDetail:
    page_url: str
    title: str
    author: str = ""
    author_id: str = ""
    workshop_id: str = ""
    size_text: str = ""
    revision: str = ""
    description: str = ""
    download_url: str = ""
    download_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- cliente --------------------------------------------------------------


def make_client(timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en,es;q=0.8"},
    )


def get_html(client: httpx.Client, url: str) -> str:
    """GET simple que respeta robots.txt y devuelve el HTML."""
    if url.startswith(SMODS_BASE) and not ROBOTS.allows(url):
        raise PermissionError(f"robots.txt no permite pedir {url}")
    r = client.get(url)
    r.raise_for_status()
    return r.text


def catalog_page(page: int = 1, client: httpx.Client | None = None) -> list[CatalogEntry]:
    """Una pagina del catalogo (10 mods, paginacion profunda incluida)."""
    own = client is None
    client = client or make_client()
    try:
        if not ROBOTS.loaded:
            ROBOTS.load(client)
        url = f"{SMODS_BASE}/page/{page}" if page > 1 else SMODS_BASE
        body = get_html(client, url)
    finally:
        if own:
            client.close()

    out: list[CatalogEntry] = []
    seen: set[str] = set()
    for href, text in RE_ARCHIVE_LINK.findall(body):
        if href in seen:
            continue
        title = html.unescape(text).strip()
        if not title or title.lower() == "read more":
            continue
        seen.add(href)
        out.append(CatalogEntry(url=href, title=title))
    return out


def parse_detail(page_url: str, body: str) -> ModDetail:
    """Extrae los datos de la ficha de un mod."""
    h1 = RE_H1.search(body)
    title = _clean(h1.group(1)) if h1 else ""

    wid = RE_WORKSHOP_ID.search(body)
    prof = RE_STEAM_PROFILE.search(body)
    author_url = RE_AUTHOR_URL.search(body)

    dl = RE_DOWNLOAD.search(body) or RE_MODSBASE_ANY.search(body)
    download_url = html.unescape(dl.group(1)) if dl else ""

    # descripcion: texto que sigue al boton de descarga
    description = ""
    m = re.search(
        r"Description:?\s*</[^>]+>(.*?)(?:<div[^>]*class=\"[^\"]*skymods-sidebar|</article)",
        body,
        re.S | re.I,
    )
    if m:
        description = _clean(m.group(1))[:2000]

    return ModDetail(
        page_url=page_url,
        title=title,
        author=_clean(RE_FIELD_AUTHOR.search(body).group(1)) if RE_FIELD_AUTHOR.search(body) else "",
        author_id=(prof.group(1) if prof else (author_url.group(1) if author_url else "")),
        workshop_id=wid.group(1) if wid else "",
        size_text=_clean(RE_FIELD_SIZE.search(body).group(1)) if RE_FIELD_SIZE.search(body) else "",
        revision=_clean(RE_FIELD_REVISION.search(body).group(1))
        if RE_FIELD_REVISION.search(body)
        else "",
        description=description,
        download_url=download_url,
        download_name=download_url.rsplit("/", 1)[-1].replace(".html", "") if download_url else "",
    )


def mod_detail(url: str, client: httpx.Client | None = None) -> ModDetail:
    """Descarga y parsea la ficha de un mod."""
    if not url.startswith("http"):
        url = urljoin(f"{SMODS_BASE}/", url)
    own = client is None
    client = client or make_client()
    try:
        if not ROBOTS.loaded:
            ROBOTS.load(client)
        body = get_html(client, url)
    finally:
        if own:
            client.close()
    d = parse_detail(url, body)
    if not d.download_url:
        raise LookupError(f"La ficha {url} no expone enlace de descarga.")
    if not MODSBASE_RE.match(d.download_url):
        raise LookupError(
            f"El enlace de {d.title or url} no es de modsbase.com (usa otro hosting). "
            "CS1 Mods Installer solo soporta enlaces modsbase."
        )
    return d


def polite(seconds: float = 0.4) -> None:
    time.sleep(seconds)
