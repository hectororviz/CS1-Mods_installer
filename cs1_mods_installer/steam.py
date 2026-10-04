"""Metadata de Steam Workshop (API anonima) para clasificar y verificar.

La API publica ``GetPublishedFileDetails`` responde sin autenticacion. La usamos
porque aporta dos cosas que smods no da:

* los **tags**, que dicen si el item es un mod de codigo o un asset;
* los tags de **compatibilidad** (``1.21.1-f9-compatible``), que comparamos con
  la version del juego instalada para avisar antes de que el usuario instale
  algo incompatible.

Ojo: en CS los ficheros del Workshop se sirven autenticados y ``file_url``
viene vacio (lo verificamos: 0 de 30 items). Por eso CS1 Mods Installer no descarga de
aqui, solo lee metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import STEAM_API, USER_AGENT

# --- clasificacion por tags ------------------------------------------------
#
# El vocabulario no se inventa: se extrajo del propio Workshop. Muestreando 244
# items reales de la app 255710 y leyendo sus ``tags`` por la API anonima,
# salen solo 38 tags distintos, todos en singular y capitalizados::
#
#   Vehicle Building Map Residential Prop Mod Park Unique Building
#   Intersection Residential High SaveGame Residential Low Commercial Deathcare
#   Road Transport Commercial Low 1.21.1-f9-compatible Education Garbage
#   Scenario Map Theme Theme Mix Commercial High Transport Train Tree
#   Electricity Water & Sewage Healthcare Fire Department Police Department
#   Industrial Office Custom Effects Transport Monorail Workshop english Citizen
#
# Ojo con ``Vehicle`` (singular) frente a ``vehicles``: con el plural se
# colaba un "unknown" en la mitad de los packs de vehiculos.
#
# El orden importa: un mod de codigo que ademas lleva assets sigue siendo mod,
# porque lo que el juego carga de verdad es la DLL.

# tags que identifican un mod de codigo (DLL)
MOD_TAGS = {"mod"}

# tags de assets: edificios, props, vehiculos, redes, arboles... y tambien los
# "servicios" (Deathcare, Healthcare...), que en la practica son packs de
# edificios ConcreteLife.
ASSET_TAGS = {
    "building",
    "unique building",
    "residential",
    "residential low",
    "residential high",
    "commercial",
    "commercial low",
    "commercial high",
    "industrial",
    "office",
    "prop",
    "park",
    "vehicle",
    "transport",
    "transport train",
    "transport monorail",
    "tree",
    "intersection",
    "road",
    "citizen",
    "custom effects",
    "deathcare",
    "education",
    "garbage",
    "healthcare",
    "fire department",
    "police department",
    "electricity",
    "water & sewage",
}

THEME_TAGS = {"map theme", "theme mix"}
MAP_TAGS = {"map"}
SCENARIO_TAGS = {"scenario"}
SAVE_TAGS = {"savegame"}
# tags que no dicen nada sobre el tipo de contenido
NEUTRAL_TAGS = {"workshop", "english"}

RE_COMPAT = re.compile(r"(\d+\.\d+(?:\.\d+)*(?:-[a-zA-Z]\d+)?)-compatible", re.I)

# Todos los valores que puede devolver :func:`classify`. El instalador anade
# "style", que aqui no se puede detectar (no existe el tag); se declara en
# cs1_mods_installer.installer.KINDS. tests/ui_contract.mjs lee estas dos listas para
# comprobar que los filtros de la web las cubren todas.
KINDS = ("unknown", "mod", "asset", "theme", "map", "scenario", "savegame")


@dataclass
class SteamInfo:
    workshop_id: str
    title: str = ""
    description: str = ""
    creator: str = ""
    file_size: int = 0
    time_updated: int = 0
    preview_url: str = ""
    tags: list[str] = field(default_factory=list)
    kind: str = "unknown"  # mod | asset | theme | map | scenario | savegame | unknown
    compat: str = ""  # p.ej. 1.21.1-f9

    def to_dict(self) -> dict[str, Any]:
        return {
            "workshop_id": self.workshop_id,
            "title": self.title,
            "description": self.description,
            "creator": self.creator,
            "file_size": self.file_size,
            "time_updated": self.time_updated,
            "preview_url": self.preview_url,
            "tags": self.tags,
            "kind": self.kind,
            "compat": self.compat,
        }


def classify(tags: list[str]) -> str:
    """Deduce el tipo de contenido a partir de los tags.

    Solo sirve para lo que se ve **antes** de descargar. El destino real lo
    decide el contenido del .zip (ver :mod:`cs1_mods_installer.installer`), porque el
    Workshop etiqueta a veces de forma generosa: un mod con assets sale como
    ``Mod``, y hay packs de edificios que no dicen ``Building``.
    """
    low = {t.lower().strip() for t in tags}
    # los tags de version no son un tipo de contenido
    low = {t for t in low if t and not RE_COMPAT.search(t) and t not in NEUTRAL_TAGS}
    if not low:
        return "unknown"
    if low & MOD_TAGS:
        return "mod"
    if low & SCENARIO_TAGS:
        return "scenario"
    if low & THEME_TAGS:
        return "theme"
    if low & MAP_TAGS:
        return "map"
    if low & SAVE_TAGS:
        return "savegame"
    if low & ASSET_TAGS:
        return "asset"
    return "unknown"


def compat_of(tags: list[str]) -> str:
    for t in tags:
        m = RE_COMPAT.search(t)
        if m:
            return m.group(1)
    return ""


def _parse(item: dict[str, Any]) -> SteamInfo:
    tags = [t.get("tag", "") for t in item.get("tags", []) if isinstance(t, dict)]
    return SteamInfo(
        workshop_id=str(item.get("publishedfileid", "")),
        title=str(item.get("title", "") or ""),
        description=str(item.get("description", "") or ""),
        creator=str(item.get("creator", "") or ""),
        file_size=int(item.get("file_size", 0) or 0),
        time_updated=int(item.get("time_updated", 0) or 0),
        preview_url=str(item.get("preview_url", "") or ""),
        tags=tags,
        kind=classify(tags),
        compat=compat_of(tags),
    )


def fetch(
    workshop_ids: list[str], client: httpx.Client | None = None, batch: int = 100
) -> dict[str, SteamInfo]:
    """Consulta la APIanonima en lotes de 100 y devuelve un dict por id."""
    ids = [i for i in dict.fromkeys(workshop_ids) if i and i.isdigit()]
    if not ids:
        return {}

    own = client is None
    client = client or httpx.Client(
        timeout=30.0, headers={"User-Agent": USER_AGENT}
    )
    out: dict[str, SteamInfo] = {}
    try:
        for start in range(0, len(ids), batch):
            chunk = ids[start : start + batch]
            data: dict[str, str] = {"itemcount": str(len(chunk))}
            data.update({f"publishedfileids[{i}]": v for i, v in enumerate(chunk)})
            try:
                r = client.post(STEAM_API, data=data)
                r.raise_for_status()
                payload = r.json()
            except (httpx.HTTPError, ValueError):
                continue
            for item in payload.get("response", {}).get("publishedfiledetails", []):
                if not isinstance(item, dict):
                    continue
                # result != 1 significa que el item no existe o es privado
                if int(item.get("result", 1) or 1) != 1:
                    continue
                info = _parse(item)
                if info.workshop_id:
                    out[info.workshop_id] = info
    finally:
        if own:
            client.close()
    return out


def human_size(num: int) -> str:
    step = 1024.0
    for unit in ("B", "KB", "MB", "GB"):
        if num < step or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= step
    return f"{num:.1f} GB"


def compat_status(info: SteamInfo | None, game_version: str) -> str:
    """ok | mismatch | unknown para el version del juego detectada."""
    if not info or not info.compat or not game_version:
        return "unknown"
    return "ok" if info.compat == game_version else "mismatch"
