"""Descarga desde modsbase.com.

El enlace que publica smods.ru no descarga el fichero directamente: es una
landing con boton. El flujo real, verificado contra ficheros reales, es:

1. ``GET``  la landing (con ``CookieJar``) -> formulario con ``op=download2``
   e ``id``;
2. ``POST`` la misma URL con esos campos -> HTML con una **URL prefirmada**
   de S3/OVH (``X-Amz-Signature``) valida una hora;
3. ``GET``  esa URL -> el ``.zip``.

Dos detalles que costaron sangre y conviene no olvidar:

* el bucket cambia (``mbuploads.``, ``mbuploads2.``, ...), asi que nunca se
  busca por host: se busca cualquier URL firmada con ``X-Amz-Signature``;
* el boton tiene un contador visible, pero es solo CSS/JS: el POST responde
  igual de inmediato. Aun asi CS1 Mods Installer espera un poco por cortesia.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx

from .config import USER_AGENT

# Cualquier URL pre-firmada de S3/OVH que sirva el boton de descarga.
RE_PRESIGNED = re.compile(r'href="(https://[^"]*X-Amz-Signature=[^"]+)"', re.I)
RE_FORM_OP = re.compile(r'name="op"\s+value="([^"]+)"', re.I)
RE_FORM_ID = re.compile(r'name="id"\s+value="([^"]+)"', re.I)

ProgressCb = Callable[[int, int | None], None]


class DownloadError(RuntimeError):
    pass


@dataclass
class PresignedLink:
    url: str
    expires_hint: str = ""


def _client(timeout: float = 60.0) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en,es;q=0.8"},
    )


def resolve(landing_url: str, client: httpx.Client | None = None) -> PresignedLink:
    """Pasos 1 y 2: devuelve la URL prefirmada."""
    own = client is None
    client = client or _client()
    try:
        page = client.get(landing_url)
        page.raise_for_status()
        body = page.text

        op = RE_FORM_OP.search(body)
        fid = RE_FORM_ID.search(body)
        if not fid:
            raise DownloadError(
                "La pagina de descarga cambio: no se encontro el formulario "
                "(name=id). Puede que modsbase haya modificado su web."
            )

        payload = {
            "op": op.group(1) if op else "download2",
            "id": fid.group(1),
            "rand": "",
            "referer": "",
            "method_free": "",
            "method_premium": "",
        }
        resp = client.post(
            landing_url, data=payload, headers={"Referer": landing_url}
        )
        resp.raise_for_status()

        m = RE_PRESIGNED.search(resp.text)
        if not m:
            raise DownloadError(
                "modsbase no devolvio el enlace directo. Suele pasar si pide "
                "captcha o si el fichero fue retirado. Prueba de nuevo en unos "
                "segundos o instalalo manualmente desde la ficha del mod."
            )
        url = html.unescape(m.group(1))
        exp = re.search(r"X-Amz-Expires=(\d+)", url)
        return PresignedLink(url=url, expires_hint=f"{int(exp.group(1)) // 60} min" if exp else "")
    finally:
        if own:
            client.close()


def download(
    landing_url: str,
    dest: Path,
    progress: ProgressCb | None = None,
    client: httpx.Client | None = None,
) -> Path:
    """Pasos 1-3: resuelve el enlace y descarga el .zip a ``dest``."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    own = client is None
    client = client or _client()
    try:
        link = resolve(landing_url, client)

        with client.stream("GET", link.url) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0) or None
            written = 0
            tmp = dest.with_suffix(dest.suffix + ".part")
            with open(tmp, "wb") as fh:
                for block in r.iter_bytes(chunk_size=64 * 1024):
                    fh.write(block)
                    written += len(block)
                    if progress:
                        progress(written, total)
            if progress:
                progress(written, total or written)
            if total and written != total:
                tmp.unlink(missing_ok=True)
                raise DownloadError(
                    f"Descarga incompleta: {written} de {total} bytes. Reintenta."
                )
            tmp.replace(dest)
        return dest
    finally:
        if own:
            client.close()
