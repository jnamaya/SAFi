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


def _chunk_offsets(raw, kind):
    """Byte offsets of every chunk of `kind` in a PNG, for reading raw pixels
    without pulling in an image library the test environment need not have."""
    from struct import unpack
    i = 8
    while i < len(raw) - 8:
        length = unpack(">I", raw[i:i + 4])[0]
        if raw[i + 4:i + 8] == kind:
            yield i
        i += 12 + length


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

    def test_one_icon_file_serves_every_purpose(self):
        """Deliberately one file, not four (2026-08-11). It is padded into the
        inner 80% safe zone, so the same PNG is safe under a launcher mask,
        opaque enough for iOS, and legible unmasked. Fewer assets to
        regenerate when the brand changes, which is the whole reason.

        Removing icons ALTOGETHER was considered and rejected: the sidebar
        logo lives inside the page and can never reach the dock, and there is
        no favicon to fall back on, so an installed app would show a blank
        tile — the dock icon is the only visible artefact the manifest
        produces."""
        self.assertEqual(len(MANIFEST["icons"]), 1)
        self.assertEqual(MANIFEST["icons"][0]["sizes"], "512x512")

    def test_the_single_icon_declares_both_purposes(self):
        """`purpose` is a space-separated list; one file can be both."""
        purpose = MANIFEST["icons"][0]["purpose"].split()
        self.assertIn("any", purpose)
        self.assertIn("maskable", purpose)

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
        self.assertEqual(path.name, MANIFEST["icons"][0]["src"].split("/")[-1],
                         "iOS should reuse the one icon, not a second file")
        from struct import unpack
        head = path.read_bytes()[:26]
        # PNG colour type is byte 25; 6 = RGBA (has alpha), 2 = RGB.
        self.assertNotEqual(head[25], 6, "apple-touch-icon must not have alpha")

    def test_the_icon_is_opaque(self):
        """A mask crops to a shape, and iOS composites onto white; transparent
        corners lose under both."""
        icon = MANIFEST["icons"][0]
        head = (PUBLIC / icon["src"].lstrip("/")).read_bytes()[:26]
        self.assertNotEqual(head[25], 6, "the icon must not have alpha")

    def test_the_splash_matches_the_mark(self):
        """background_color paints the launch screen behind the icon, so a
        mismatch flashes the wrong colour before the icon appears.

        Read out of the icon itself rather than hard-coded. The literal used
        to be "#333333" for the dark tile, went stale the moment the mark
        changed to the four-petal wordmark on white (2026-08-25), and failed
        as a stale assertion rather than as the real defect. Deriving it means
        the next mark cannot drift from its own splash.
        """
        import zlib
        from struct import unpack
        raw = (PUBLIC / MANIFEST["icons"][0]["src"].lstrip("/")).read_bytes()
        w, h = unpack(">II", raw[16:24])
        # Decode enough of the PNG to read pixel (0, 0): the icon is full-bleed,
        # so its corner IS the field colour the splash has to match.
        idat = b"".join(
            raw[i + 8:i + 8 + unpack(">I", raw[i:i + 4])[0]]
            for i in _chunk_offsets(raw, b"IDAT")
        )
        line = zlib.decompress(idat)[:4]
        # line[0] is the row's filter type, and it does not matter here: for
        # the very FIRST pixel every PNG filter (None/Sub/Up/Average/Paeth)
        # has no left or upper neighbour, so each predicts zero and the stored
        # bytes are the raw colour. Reading them is valid whatever the encoder
        # chose. This icon ships as filter type 1.
        corner = "#%02x%02x%02x" % (line[1], line[2], line[3])
        self.assertEqual(MANIFEST["background_color"].lower(), corner,
                         f"splash {MANIFEST['background_color']} does not match "
                         f"the icon's own field {corner}")


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
