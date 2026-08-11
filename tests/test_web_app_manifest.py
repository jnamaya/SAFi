"""
The web app manifest: installable, and caching nothing.

WHY. There was no manifest and no service worker, so the web app could not be
installed at all — no dock icon, no standalone window, browser tab only. That
is most of what people mean by "desktop app" for a chat product, and it costs
one JSON file rather than an Electron shell (which, on the evidence of the
Capacitor client, would arrive with its own origin model and its own class of
bugs).

The deliberate omission is the service worker. Chrome/Edge want a fetch handler
before offering their install button, and we accept losing that, because:

  * The org default is `offline_enabled: false` — no local copies of org
    content on the device. A stock caching recipe would cache /api responses
    and quietly break a guarantee the Compliance tab advertises.
  * A badly versioned SW serves stale code that a refresh cannot fix.

So this file pins the absence as much as the presence. If a service worker is
ever added, these tests should be UPDATED deliberately, not deleted quietly —
that is the point of them.

Run:  venv/bin/python tests/test_web_app_manifest.py
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PUBLIC = ROOT / "public"
MANIFEST_PATH = PUBLIC / "manifest.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
INDEX = (PUBLIC / "index.html").read_text(encoding="utf-8")


class TheManifestIsInstallable(unittest.TestCase):

    def test_required_fields_present(self):
        for key in ("name", "short_name", "start_url", "scope", "display", "icons"):
            self.assertIn(key, MANIFEST)

    def test_standalone_display(self):
        """The whole point: its own window, no URL bar."""
        self.assertEqual(MANIFEST["display"], "standalone")

    def test_scope_and_start_url_match_how_flask_serves_public(self):
        """`static_url_path='/'`, so the app lives at the domain root and
        /manifest.json resolves with no new route."""
        self.assertEqual(MANIFEST["scope"], "/")
        self.assertTrue(MANIFEST["start_url"].startswith("/"))

    def test_short_name_fits_a_dock_label(self):
        self.assertLessEqual(len(MANIFEST["short_name"]), 12)

    def test_it_is_linked_from_the_page(self):
        self.assertIn('rel="manifest"', INDEX)
        self.assertIn('href="manifest.json"', INDEX)


class EveryIconItNamesExists(unittest.TestCase):
    """A manifest naming a missing icon fails silently in the browser — the
    install simply offers a blank tile, with nothing in the console."""

    def test_icon_files_are_present_and_the_right_size(self):
        from struct import unpack
        for icon in MANIFEST["icons"]:
            rel = icon["src"].lstrip("/")
            path = PUBLIC / rel
            with self.subTest(icon=rel):
                self.assertTrue(path.exists(), f"{rel} is declared but missing")
                # PNG header: width/height are big-endian uint32 at byte 16.
                head = path.read_bytes()[:24]
                self.assertEqual(head[:8], b"\x89PNG\r\n\x1a\n", "not a PNG")
                w, h = unpack(">II", head[16:24])
                declared = icon["sizes"].split("x")[0]
                self.assertEqual((w, h), (int(declared), int(declared)))

    def test_the_two_sizes_browsers_actually_want(self):
        sizes = {i["sizes"] for i in MANIFEST["icons"]}
        self.assertIn("192x192", sizes)
        self.assertIn("512x512", sizes)

    def test_a_maskable_icon_exists(self):
        """Without one, Android crops a full-bleed square to its inner circle
        and takes the artwork's edges with it."""
        purposes = {i.get("purpose") for i in MANIFEST["icons"]}
        self.assertIn("maskable", purposes)

    def test_ios_gets_its_own_link(self):
        """iOS ignores the manifest's icons for Add to Home Screen."""
        self.assertIn('rel="apple-touch-icon"', INDEX)

    def test_the_ios_icon_is_opaque(self):
        """iOS composites apple-touch-icon onto WHITE and applies its own
        rounding. The transparent circle would show white corners inside the
        rounded tile, so iOS gets the full-bleed square."""
        import re as _re
        m = _re.search(r'rel="apple-touch-icon"\s+href="([^"]+)"', INDEX)
        self.assertIsNotNone(m)
        path = PUBLIC / m.group(1).lstrip("/")
        self.assertTrue(path.exists(), f"{m.group(1)} is missing")
        from struct import unpack
        head = path.read_bytes()[:26]
        # PNG colour type is byte 25; 6 = RGBA (has alpha), 2 = RGB.
        self.assertNotEqual(head[25], 6, "apple-touch-icon must not have alpha")

    def test_the_maskable_icon_is_opaque_too(self):
        """A mask crops to a shape; transparent corners under it defeat the
        purpose of declaring one."""
        mask = [i for i in MANIFEST["icons"] if i.get("purpose") == "maskable"][0]
        head = (PUBLIC / mask["src"].lstrip("/")).read_bytes()[:26]
        self.assertNotEqual(head[25], 6, "maskable icon must not have alpha")

    def test_the_splash_matches_the_mark(self):
        """background_color paints the launch screen behind the icon; the
        mark is dark (#333), so a white splash flashes white first."""
        self.assertEqual(MANIFEST["background_color"].lower(), "#333333")


class NothingIsCached(unittest.TestCase):

    def test_no_service_worker_is_registered(self):
        """See the module docstring. If this fails because a SW was added
        on purpose, update this file and item 35 together."""
        for f in PUBLIC.rglob("*.js"):
            if "node_modules" in f.parts or "lib" in f.parts:
                continue
            src = f.read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn("serviceWorker.register", src,
                             f"{f.relative_to(PUBLIC)} registers a service worker")

    def test_no_service_worker_file_at_the_root(self):
        for name in ("sw.js", "service-worker.js", "workbox-sw.js"):
            self.assertFalse((PUBLIC / name).exists(), f"{name} exists")

    def test_the_manifest_declares_no_caching_hints(self):
        self.assertNotIn("serviceworker", {k.lower() for k in MANIFEST})


class ItIsThemeAware(unittest.TestCase):

    def test_both_theme_colors_are_declared(self):
        """The UI is dark-capable (dark:bg-black); one light value leaves a
        white title bar above a black app."""
        self.assertIn('media="(prefers-color-scheme: light)"', INDEX)
        self.assertIn('media="(prefers-color-scheme: dark)"', INDEX)


if __name__ == "__main__":
    unittest.main(verbosity=2)
