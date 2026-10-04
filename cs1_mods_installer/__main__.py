"""Punto de entrada de CS1 Mods Installer.

Levanta el servidor local en 127.0.0.1 y abre el navegador del sistema. Se
pensa para lanzarse desde un icono de aplicacion, no para teclear comandos.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser

from .config import APP_TITLE, detect_game, ensure_dirs, save_settings, load_settings


def _free_port(preferred: int, host: str = "127.0.0.1") -> int:
    """Puerto libre, intentando primero el preferido."""
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise OSError("No se encontro un puerto libre")


def _wait_for(url: str, timeout: float = 25.0) -> bool:
    import httpx

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return True
        except Exception:
            time.sleep(0.3)
    return False


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cs1-mods-installer",
        description=f"{APP_TITLE} · gestor de mods para Cities: Skylines",
    )
    p.add_argument("--port", type=int, default=8787, help="puerto (por defecto 8787)")
    p.add_argument("--host", default="127.0.0.1", help="interfaz (solo local por defecto)")
    p.add_argument("--game-dir", default=None, help="carpeta de Cities: Skylines")
    p.add_argument("--no-browser", action="store_true", help="no abrir el navegador")
    p.add_argument("--no-serve", action="store_true", help="solo mostrar como quedo todo y salir")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ensure_dirs()

    if args.game_dir:
        save_settings({**load_settings(), "game_dir": os.path.abspath(args.game_dir)})

    game = detect_game(args.game_dir)
    if game is None:
        print("✗ No se encontró Cities: Skylines.")
        print("  Indica la carpeta del juego, por ejemplo:")
        print("     cs1-mods-installer --game-dir ~/Games/Heroic/CitiesSkylines")
        return 2

    print(f"✓ Juego detectado: {game.install_dir}")
    print(f"  versión : {game.version or 'desconocida'}")
    print(f"  launcher: {game.launcher or 'desconocido'}")
    print(f"  mods    : {game.mods_dir}")
    print(f"  assets  : {game.assets_dir}")
    for w in game.warnings:
        print(f"  ! {w}")

    if args.no_serve:
        return 0

    from .server import app  # se importa tarde para no cargar todo al imprimir

    port = _free_port(args.port, args.host)
    url = f"http://{args.host}:{port}/"

    if not args.no_browser:
        # el navegador se abre cuando el servidor ya responde
        threading.Thread(
            target=lambda: _wait_for(url + "health") and webbrowser.open(url),
            daemon=True,
        ).start()

    print(f"\n  {APP_TITLE} en {url}")
    print("  Ctrl+C para detener.\n")

    try:
        import uvicorn

        uvicorn.run(app, host=args.host, port=port, log_level="warning")
    except KeyboardInterrupt:
        print("\n  Cerrando.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
