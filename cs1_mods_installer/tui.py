"""Interfaz TUI (terminal) para CS1 Mods Installer, con Textual.

Es texto puro: sin navegador, sin imagenes, sin JS. Por eso pinta
más rápido que la web: la lista parcial aparece en cuanto llega el
índice/página de smods y los metadatos (tipo, tamaño, autor) se
rellenan en segundo plano con el mismo ``enrich_batch`` de la web.
"""

from __future__ import annotations

from typing import Any

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    Static,
)

from . import catalog, installer
from .config import detect_game
from .jobs import REGISTRY


def _short(card: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """Fila de la tabla a partir de un dict de tarjeta."""
    mark = "✓ " if card.get("installed") else ("…" if card.get("partial") else "")
    title = f"{mark}{card.get('title', '¿?')}"
    if len(title) > 52:
        title = title[:51] + "…"
    kind = str(card.get("kind") or "?")
    size = str(card.get("size_text") or "")
    author = str(card.get("author") or "")
    if len(author) > 20:
        author = author[:19] + "…"
    compat = str(card.get("compat") or "")
    return (title, kind, size, author, compat)


class DetailScreen(Screen):
    """Ficha del mod con botón de instalar."""

    BINDINGS = [Binding("escape", "close", "Cerrar")]

    CSS = """
    DetailScreen { align: center middle; }
    #box {
        width: 76; height: auto; max-height: 90%;
        border: tall $primary; padding: 1 2; background: $surface;
    }
    #dtitle { text-style: bold; margin-bottom: 1; }
    .row { margin-bottom: 1; }
    """

    def __init__(self, card: dict[str, Any], game: Any) -> None:
        super().__init__()
        self.card = card
        self.game = game
        self._job = None
        self._timer = None

    def compose(self) -> ComposeResult:
        c = self.card
        tags = ", ".join(c.get("tags") or [])
        with Vertical(id="box"):
            yield Label(c.get("title", "¿?"), id="dtitle")
            yield Static(f"Tipo: {c.get('kind')}  ·  Tamaño: {c.get('size_text')}", classes="row")
            yield Static(f"Autor: {c.get('author')}  ·  Revisión: {c.get('revision')}", classes="row")
            yield Static(f"Juego: {c.get('compat') or '?'} [{c.get('compat_status')}]", classes="row")
            yield Static(f"Tags: {tags or '—'}", classes="row")
            yield Static(f"ID: {c.get('workshop_id') or '¿?'}", classes="row")
            yield Static(
                "Instalado: sí" if c.get("installed") else "Instalado: no", classes="row"
            )
            yield ProgressBar(id="prog", show_eta=False)
            yield Static("", id="msg")
            with Horizontal():
                yield Button("Instalar", id="do_install", variant="primary")
                yield Button("Cerrar", id="do_close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "do_close":
            self.action_close()
        elif event.button.id == "do_install":
            self._start_install()

    def action_close(self) -> None:
        if self._timer:
            self._timer.stop()
        self.dismiss()

    def _start_install(self) -> None:
        if self.game is None:
            self.query_one("#msg", Static).update("Sin juego detectado.")
            return
        self.query_one("#msg", Static).update("Instalando…")
        self._job = REGISTRY.create("install", self.card.get("title", ""))
        REGISTRY.run(
            self._job, lambda j: catalog.install_job(j, self.card["url"], self.game)
        )
        self._timer = self.set_interval(0.3, self._poll)

    def _poll(self) -> None:
        job = self._job
        if job is None:
            return
        try:
            self.query_one("#prog", ProgressBar).update(progress=job.progress)
        except Exception:
            pass
        msg = job.step or job.state
        if job.state == "done":
            extra = (job.detail.get("installed") or {}).get("path", "")
            self.query_one("#msg", Static).update(f"Listo. {extra}")
            if self._timer:
                self._timer.stop()
        elif job.state == "error":
            self.query_one("#msg", Static).update(f"Error: {job.error}")
            if self._timer:
                self._timer.stop()
        else:
            self.query_one("#msg", Static).update(msg)


class CS1TUI(App):
    """TUI principal: catálogo rápido + instalados."""

    CSS = """
    #bar { height: 3; margin: 0 1; }
    #search { width: 1fr; }
    #table { margin: 0 1; height: 1fr; }
    #status { padding: 0 1; text-style: dim; height: 1; }
    """

    BINDINGS = [
        Binding("q", "quit", "Salir"),
        Binding("/", "focus_search", "Buscar"),
        Binding("1", "view_catalog", "Catálogo"),
        Binding("2", "view_installed", "Instalados"),
        Binding("n", "next_page", "Pág.+"),
        Binding("p", "prev_page", "Pág.−"),
        Binding("r", "reload", "Recargar"),
        Binding("enter", "open_detail", "Detalle"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.game = detect_game()
        self.mode = "catalog"  # catalog | installed
        self.page = 1
        self.cards: list[dict[str, Any]] = []
        self.by_row: dict[str, dict[str, Any]] = {}

    def compose(self) -> ComposeResult:
        title = "CS1 Mods — TUI"
        yield Header(show_clock=False)
        self.title = title
        with Horizontal(id="bar"):
            yield Input(placeholder="/ buscar…  (Enter busca, Esc limpia)", id="search")
            yield Button("Buscar", id="go_search", variant="primary")
            yield Button("Instalados [2]", id="go_inst")
        table = DataTable(id="table", cursor_type="row")
        table.add_column("Mod", width=54)
        table.add_column("Tipo", width=10)
        table.add_column("Tamaño", width=10)
        table.add_column("Autor", width=22)
        table.add_column("Juego", width=10)
        yield table
        yield Static("…", id="status")
        yield Footer()

    # -- arranque ------------------------------------------------------

    def on_mount(self) -> None:
        if self.game is None:
            self.set_status("No se detectó el juego. Sal con q y pasa --game-dir.")
            return
        self.set_status(f"Juego: {self.game.install_dir} · cargando página 1…")
        self.load_catalog()

    def set_status(self, msg: str) -> None:
        try:
            self.query_one("#status", Static).update(msg)
        except Exception:
            pass

    # -- carga del catálogo (parcial primero, enrich después) -----------

    @work(thread=True)
    def load_catalog(self) -> None:
        try:
            cards = catalog.browse(self.page, self.game)
            self.cards = [c.to_dict() for c in cards]
            self.call_from_thread(self.paint_cards, f"pág. {self.page} · completando datos…")
            urls = [c["url"] for c in self.cards if c.get("partial")]
            if urls:
                enriched = catalog.enrich_batch(urls, self.game)
                emap = {c.url: c.to_dict() for c in enriched}
                for i, c in enumerate(self.cards):
                    if c["url"] in emap:
                        self.cards[i] = emap[c["url"]]
                self.call_from_thread(
                    self.paint_cards, f"pág. {self.page} · {len(self.cards)} mods · n/p cambia de página"
                )
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.set_status, f"Error: {e}")

    @work(thread=True)
    def run_search(self, query: str) -> None:
        try:
            self.call_from_thread(self.set_status, f"Buscando «{query}»…")
            cards = catalog.search(query, self.game, limit=40)
            self.cards = [c.to_dict() for c in cards]
            self.call_from_thread(self.paint_cards, f"{len(self.cards)} resultados · completando…")
            urls = [c["url"] for c in self.cards if c.get("partial")]
            if urls:
                enriched = catalog.enrich_batch(urls, self.game)
                emap = {c.url: c.to_dict() for c in enriched}
                for i, c in enumerate(self.cards):
                    if c["url"] in emap:
                        self.cards[i] = emap[c["url"]]
                self.call_from_thread(
                    self.paint_cards, f"{len(self.cards)} resultados para «{query}»"
                )
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.set_status, f"Error buscando: {e}")

    @work(thread=True)
    def load_installed(self) -> None:
        try:
            items = installer.list_installed(self.game) if self.game else []
            rows = [i.to_dict() for i in items]
            self.call_from_thread(self.paint_installed, rows)
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.set_status, f"Error: {e}")

    # -- pintado --------------------------------------------------------

    def paint_cards(self, msg: str = "") -> None:
        self.mode = "catalog"
        table = self.query_one("#table", DataTable)
        table.clear()
        self.by_row = {}
        for c in self.cards:
            key = c["url"]
            table.add_row(*_short(c), key=key)
            self.by_row[key] = c
        if msg:
            self.set_status(msg)

    def paint_installed(self, rows: list[dict[str, Any]]) -> None:
        self.mode = "installed"
        table = self.query_one("#table", DataTable)
        table.clear()
        self.by_row = {}
        for i in rows:
            key = i.get("path", i.get("folder", ""))
            state = "off" if not i.get("enabled") else ("ok" if i.get("managed") else "juego")
            table.add_row(
                i.get("title", "?")[:52],
                i.get("kind", "?"),
                "",
                state,
                i.get("folder", "")[:10],
                key=key,
            )
            self.by_row[key] = i
        self.set_status(f"{len(rows)} instalados · Enter alterna activar/desactivar · 1 vuelve al catálogo")

    def selected_card(self) -> dict[str, Any] | None:
        table = self.query_one("#table", DataTable)
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            return self.by_row.get(str(row_key.value))
        except Exception:
            return None

    # -- eventos --------------------------------------------------------

    @on(Input.Submitted)
    def _on_search_submit(self, event: Input.Submitted) -> None:
        q = event.value.strip()
        if q:
            self.mode = "catalog"
            self.run_search(q)

    @on(Button.Pressed)
    def _on_btn(self, event: Button.Pressed) -> None:
        if event.button.id == "go_search":
            q = self.query_one("#search", Input).value.strip()
            if q:
                self.mode = "catalog"
                self.run_search(q)
        elif event.button.id == "go_inst":
            self.action_view_installed()

    @on(DataTable.RowSelected)
    def _on_row(self, event: DataTable.RowSelected) -> None:
        key = str(event.row_key.value)
        data = self.by_row.get(key)
        if data is None:
            return
        if self.mode == "catalog":
            self.push_screen(DetailScreen(data, self.game))
        else:
            self.toggle_installed(data)

    @work(thread=True)
    def toggle_installed(self, data: dict[str, Any]) -> None:
        from pathlib import Path

        try:
            if self.game is None:
                return
            new_state = not data.get("enabled", True)
            installer.set_enabled(Path(data["path"]), new_state)
            self.call_from_thread(
                self.set_status,
                f"{data.get('title', '?')}: {'activado' if new_state else 'desactivado'}",
            )
            self.load_installed()
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.set_status, f"Error: {e}")

    # -- acciones de teclado --------------------------------------------

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_view_catalog(self) -> None:
        self.mode = "catalog"
        self.load_catalog()

    def action_view_installed(self) -> None:
        self.load_installed()

    def action_next_page(self) -> None:
        if self.mode != "catalog":
            return
        self.page += 1
        self.set_status(f"Cargando página {self.page}…")
        self.load_catalog()

    def action_prev_page(self) -> None:
        if self.mode != "catalog" or self.page <= 1:
            return
        self.page -= 1
        self.set_status(f"Cargando página {self.page}…")
        self.load_catalog()

    def action_reload(self) -> None:
        if self.mode == "catalog":
            self.load_catalog()
        else:
            self.load_installed()

    def action_open_detail(self) -> None:
        data = self.selected_card()
        if data is None:
            return
        if self.mode == "catalog":
            self.push_screen(DetailScreen(data, self.game))
        else:
            self.toggle_installed(data)


def main() -> None:
    """Punto de entrada de la TUI."""
    CS1TUI().run()


if __name__ == "__main__":
    main()
