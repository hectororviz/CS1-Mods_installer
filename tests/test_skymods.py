"""Tests de CS1 Mods Installer. Solo biblioteca estandar: ``python -m unittest``.

    python -m unittest discover -s tests -v

El foco es lo que no se ve al usar la web: que un zip no pueda escribir fuera
del juego, que el destino se elija por el contenido y no por una etiqueta, y
que no se borre nada fuera de las carpetas de contenido.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cs1_mods_installer import index, installer, steam  # noqa: E402
from cs1_mods_installer.config import GameInstall  # noqa: E402
from cs1_mods_installer.smods import Robots  # noqa: E402


def make_zip(path: Path, entries: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return path


class FakeGame(unittest.TestCase):
    """Instalacion de juego en un temporal, para no tocar el real."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="cs1mods-test-")
        self.root = Path(self.tmp.name)
        self.game = GameInstall(
            install_dir=self.root,
            content_root=self.root / "Files",
            version="1.21.1-f9",
        )
        (self.game.mods_dir).mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()


class TestSeguridadZip(FakeGame):
    def test_bloquea_path_traversal(self) -> None:
        z = make_zip(self.root / "evil.zip", {"../../etc/passwd": "pwn"})
        with self.assertRaises(installer.UnsafeArchive):
            installer.safe_extract(z, self.root / "out")

    def test_bloquea_ruta_absoluta(self) -> None:
        z = make_zip(self.root / "abs.zip", {"/etc/passwd": "pwn"})
        with self.assertRaises(installer.UnsafeArchive):
            installer.safe_extract(z, self.root / "out")

    def test_bloquea_ruta_windows(self) -> None:
        z = make_zip(self.root / "win.zip", {"C:\\Windows\\evil.dll": "pwn"})
        with self.assertRaises(installer.UnsafeArchive):
            installer.safe_extract(z, self.root / "out")

    def test_bloquea_symlink(self) -> None:
        z = self.root / "link.zip"
        with zipfile.ZipFile(z, "w") as f:
            info = zipfile.ZipInfo("enlace")
            info.external_attr = 0o120777 << 16  # S_IFLNK
            f.writestr(info, "/etc/passwd")
        with self.assertRaises(installer.UnsafeArchive):
            installer.safe_extract(z, self.root / "out")

    def test_rechaza_zip_bomb(self) -> None:
        z = make_zip(self.root / "bomb.zip", {"datos.txt": "x" * 4096})
        original = installer.MAX_UNCOMPRESSED
        installer.MAX_UNCOMPRESSED = 100  # menos que el zip
        try:
            with self.assertRaises(installer.UnsafeArchive):
                installer.safe_extract(z, self.root / "out")
        finally:
            installer.MAX_UNCOMPRESSED = original

    def test_extrae_zip_normal(self) -> None:
        z = make_zip(
            self.root / "ok.zip",
            {"123 Mod/Mod.dll": "x", "123 Mod/sub/leeme.txt": "y"},
        )
        out = self.root / "out"
        n = installer.safe_extract(z, out)
        self.assertEqual(n, 2)
        self.assertTrue((out / "123 Mod" / "Mod.dll").is_file())


class TestClasificacion(FakeGame):
    def test_dll_es_mod(self) -> None:
        z = make_zip(self.root / "m.zip", {"1 A/A.dll": "x"})
        self.assertEqual(installer.inspect_zip(z).kind, "mod")

    def test_crp_es_asset(self) -> None:
        z = make_zip(self.root / "a.zip", {"1 A/A.crp": "x"})
        self.assertEqual(installer.inspect_zip(z).kind, "asset")

    def test_dll_gana_sobre_crp(self) -> None:
        """Un mod de codigo que ademas lleva assets sigue yendo a Mods/."""
        z = make_zip(self.root / "b.zip", {"1 A/A.dll": "x", "1 A/A.crp": "y"})
        info = installer.inspect_zip(z)
        self.assertEqual(info.kind, "mod")

    def test_style_xml_es_style(self) -> None:
        z = make_zip(self.root / "s.zip", {"1 A/A.style.xml": "x"})
        self.assertEqual(installer.inspect_zip(z).kind, "style")

    def test_zip_sin_contenido_reconocido(self) -> None:
        z = make_zip(self.root / "n.zip", {"1 A/leeme.txt": "x"})
        self.assertEqual(installer.inspect_zip(z).kind, "unknown")

    def test_instalar_zip_desconocido_falla(self) -> None:
        z = make_zip(self.root / "n.zip", {"1 A/leeme.txt": "x"})
        with self.assertRaises(ValueError):
            installer.install(z, self.game, workshop_id="1")

    def test_carpeta_destino_segun_contenido(self) -> None:
        self.assertEqual(
            installer.dest_dir_for(self.game, "mod"), self.game.mods_dir
        )
        self.assertEqual(
            installer.dest_dir_for(self.game, "asset"), self.game.assets_dir
        )

    def test_quita_la_carpeta_raiz_unica(self) -> None:
        z = make_zip(self.root / "m.zip", {"1 A/A.dll": "x"})
        installer.install(z, self.game, title="A", workshop_id="1")
        final = self.game.mods_dir / "1 A"
        self.assertTrue((final / "A.dll").is_file())
        self.assertFalse((final / "1 A").exists(), "no debe quedar anidado")


class TestSafeName(unittest.TestCase):
    def test_limpia_caracteres_de_control(self) -> None:
        self.assertNotIn("/", installer.safe_name("a/b\\c"))

    def test_no_deja_escapar_con_puntos(self) -> None:
        """El titulo viene del <h1> de smods.ru: texto libre.

        Sin limpiar, "<h1>../../evil</h1>" creaba la carpeta FUERA del
        directorio de contenido del juego. Esto lo encontre con el test, no
        leyendo el codigo.
        """
        for sucio in ("../../evil", "..", "a/../../b", "./../x"):
            limpio = installer.safe_name(sucio)
            self.assertNotIn("/", limpio, sucio)
            self.assertNotIn("\\", limpio, sucio)
            self.assertNotIn("..", limpio, sucio)

    def test_no_deja_carpeta_vacia(self) -> None:
        self.assertTrue(installer.safe_name("   "))
        self.assertTrue(installer.safe_name("///"))

    def test_acorta_nombres_absurdos(self) -> None:
        self.assertLessEqual(len(installer.safe_name("x" * 500)), 120)


class TestDestinoNoEscapable(FakeGame):
    """El nombre de la carpeta final nunca puede salirse de Files/."""

    def test_titulo_malicioso_no_escapa(self) -> None:
        z = make_zip(self.root / "m.zip", {"1 x/x.dll": "x"})
        rec = installer.install(
            z, self.game, title="../../../etc/cs1mods", workshop_id="999"
        )
        final = Path(rec.path)
        self.assertTrue(
            final.resolve().is_relative_to(self.game.content_root.resolve()),
            f"{final} se ha escapado de {self.game.content_root}",
        )
        self.assertEqual(final.parent, self.game.mods_dir)


class TestDesinstalar(FakeGame):
    def test_rechaza_borrar_fuera_del_juego(self) -> None:
        fuera = self.root / "importante"
        fuera.mkdir()
        with self.assertRaises(ValueError):
            installer.uninstall(fuera)

    def test_borra_dentro_de_mods(self) -> None:
        d = self.game.mods_dir / "algo"
        d.mkdir()
        (d / "x.dll").write_text("x")
        self.assertTrue(installer.uninstall(d))
        self.assertFalse(d.exists())

    def test_no_falla_si_no_existe(self) -> None:
        self.assertFalse(installer.uninstall(self.game.mods_dir / "nada"))


class TestEnableDisable(FakeGame):
    def test_mueve_la_carpera(self) -> None:
        d = self.game.mods_dir / "mod-x"
        d.mkdir()
        (d / "x.dll").write_text("x")
        # el estado real es global del usuario; aqui solo comprobamos el
        # movimiento y lo devolvemos a su sitio
        import cs1_mods_installer.installer as I

        original = I.disabled_root
        I.disabled_root = lambda: self.root / "disabled"
        try:
            self.assertTrue(I.set_enabled(d, False))
            self.assertFalse(d.exists())
            self.assertTrue((self.root / "disabled" / "mod-x").is_dir())
            self.assertTrue(I.set_enabled(d, True))
            self.assertTrue(d.is_dir())
        finally:
            I.disabled_root = original


class TestRobots(unittest.TestCase):
    def setUp(self) -> None:
        self.r = Robots()
        self.r.rules = [
            ("/?s=", True),
            ("/category", True),
            ("/wp-content", True),
            ("/archives", False),
        ]

    def test_bloquea_busqueda(self) -> None:
        self.assertFalse(self.r.allows("https://smods.ru/?s=traffic"))

    def test_bloquea_categoria(self) -> None:
        self.assertFalse(self.r.allows("https://smods.ru/category/mods"))

    def test_permite_ficha(self) -> None:
        self.assertTrue(self.r.allows("https://smods.ru/archives/126575"))

    def test_permite_paginacion(self) -> None:
        self.assertTrue(self.r.allows("https://smods.ru/page/500"))

    def test_gana_la_regla_mas_larga(self) -> None:
        self.r.rules = [("/", True), ("/archives/123", False)]
        self.assertTrue(self.r.allows("https://smods.ru/archives/123"))
        self.assertFalse(self.r.allows("https://smods.ru/otra"))


class TestClasificarTags(unittest.TestCase):
    """Tags tomados de 244 items reales del Workshop."""

    def test_mod(self) -> None:
        self.assertEqual(steam.classify(["Mod"]), "mod")

    def test_vehicle_en_singular(self) -> None:
        # el bug real: la lista tenia "vehicles" y Steam usa "Vehicle"
        self.assertEqual(steam.classify(["Vehicle"]), "asset")

    def test_servicios_son_assets(self) -> None:
        self.assertEqual(steam.classify(["Building", "Deathcare"]), "asset")

    def test_mapa(self) -> None:
        self.assertEqual(steam.classify(["Map"]), "map")

    def test_tema(self) -> None:
        self.assertEqual(steam.classify(["Map Theme"]), "theme")

    def test_guardada(self) -> None:
        self.assertEqual(steam.classify(["SaveGame"]), "savegame")

    def test_mod_gana_a_asset(self) -> None:
        self.assertEqual(steam.classify(["Mod", "Building"]), "mod")

    def test_tag_de_version_no_es_un_tipo(self) -> None:
        self.assertEqual(steam.classify(["1.21.1-f9-compatible"]), "unknown")

    def test_compat_se_extrae(self) -> None:
        self.assertEqual(steam.compat_of(["1.21.1-f5-compatible"]), "1.21.1-f5")

    def test_compat_status(self) -> None:
        info = steam.SteamInfo(workshop_id="1", compat="1.21.1-f5")
        self.assertEqual(steam.compat_status(info, "1.21.1-f9"), "mismatch")
        self.assertEqual(
            steam.compat_status(steam.SteamInfo("1", compat="1.21.1-f9"), "1.21.1-f9"),
            "ok",
        )
        self.assertEqual(steam.compat_status(None, "1.21.1-f9"), "unknown")


class TestIndice(unittest.TestCase):
    def setUp(self) -> None:
        self.idx = index.Index(
            entries=[
                {"url": "u1", "title": "Cemetery"},
                {"url": "u2", "title": "Large Cemetery"},
                {"url": "u3", "title": "Church and cemetery"},
                {"url": "u4", "title": "Traffic Manager Plus"},
            ],
            pages=1,
            built_at="",
        )

    def test_exacto_primero(self) -> None:
        self.assertEqual(index.search(self.idx, "cemetery")[0]["title"], "Cemetery")

    def test_ignora_mayusculas(self) -> None:
        self.assertEqual(index.search(self.idx, "CEMETERY")[0]["title"], "Cemetery")

    def test_encuentra_por_palabra(self) -> None:
        self.assertTrue(index.search(self.idx, "traffic"))

    def test_sin_coincidencias(self) -> None:
        self.assertEqual(index.search(self.idx, "zzzz"), [])

    def test_vacio(self) -> None:
        self.assertEqual(index.search(self.idx, ""), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)