import json
import sys
import unittest
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PUBLIC = ROOT / "public"
MANIFEST_PATH = PUBLIC / "manifest.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
INDEX = (PUBLIC / "index.html").read_text(encoding="utf-8")


def _resolve(src):
    return PUBLIC / urlsplit(src).path.lstrip("/")


class TheManifestIsInstallable(unittest.TestCase):

    def test_required_fields_present(self):
        for key in ("name", "short_name", "start_url", "scope", "display", "icons"):
            self.assertIn(key, MANIFEST)

    def test_standalone_display(self):
        self.assertEqual(MANIFEST["display"], "standalone")

    def test_scope_and_start_url_match_how_flask_serves_public(self):
        self.assertEqual(MANIFEST["scope"], "/")
        self.assertTrue(MANIFEST["start_url"].startswith("/"))

    def test_short_name_fits_a_dock_label(self):
        self.assertLessEqual(len(MANIFEST["short_name"]), 12)

    def test_it_is_linked_from_the_page(self):
        self.assertIn('rel="manifest"', INDEX)
        self.assertIn('href="manifest.json"', INDEX)


def _chunk_offsets(raw, kind):
    from struct import unpack
    i = 8
    while i < len(raw) - 8:
        length = unpack(">I", raw[i:i + 4])[0]
        if raw[i + 4:i + 8] == kind:
            yield i
        i += 12 + length


def _unfiltered_rows(path):
    import zlib
    from struct import unpack as _unpack
    raw = path.read_bytes()
    w, h = _unpack(">II", raw[16:24])
    color_type = raw[25]
    bpp = {2: 1, 6: 4}.get(color_type, 3)
    idat = b"".join(
        raw[i + 8:i + 8 + _unpack(">I", raw[i:i + 4])[0]]
        for i in _chunk_offsets(raw, b"IDAT")
    )
    decoded = zlib.decompress(idat)
    stride = 1 + w * bpp
    prev = bytearray(w * bpp)
    rows = []
    for y in range(h):
        f = decoded[y * stride]
        raw_row = bytearray(decoded[y * stride + 1:(y + 1) * stride])
        out = bytearray(w * bpp)
        for x in range(w * bpp):
            a = raw_row[x]
            left = out[x - bpp] if x >= bpp else 0
            up = prev[x]
            ul = prev[x - bpp] if x >= bpp else 0
            if f == 0:
                p = a
            elif f == 1:
                p = (a + left) & 0xFF
            elif f == 2:
                p = (a + up) & 0xFF
            elif f == 3:
                p = (a + ((left + up) >> 1)) & 0xFF
            else:
                pred = left + up - ul
                pa, pb, pc = abs(pred - left), abs(pred - up), abs(pred - ul)
                pr = left if pa <= pb and pa <= pc else (up if pb <= pc else ul)
                p = (a + pr) & 0xFF
            out[x] = p
        prev = out
        rows.append(bytes(out))
    return w, h, color_type, rows


def _transparent_pixel_count(path):
    w, h, color_type, rows = _unfiltered_rows(path)
    if color_type != 6:
        return 0
    count = 0
    for row in rows:
        for x in range(3, len(row), 4):
            if row[x] != 255:
                count += 1
    return count


class EveryIconItNamesExists(unittest.TestCase):

    def test_icon_files_are_present_and_the_right_size(self):
        from struct import unpack
        for icon in MANIFEST["icons"]:
            rel = urlsplit(icon["src"]).path.lstrip("/")
            path = PUBLIC / rel
            with self.subTest(icon=rel):
                self.assertTrue(path.exists(), f"{rel} is declared but missing")
                head = path.read_bytes()[:24]
                self.assertEqual(head[:8], b"\x89PNG\r\n\x1a\n", "not a PNG")
                w, h = unpack(">II", head[16:24])
                declared = icon["sizes"].split("x")[0]
                self.assertEqual((w, h), (int(declared), int(declared)))

    def test_any_and_maskable_are_separate_files(self):
        self.assertEqual(len(MANIFEST["icons"]), 3)
        purposes = [icon["purpose"].split() for icon in MANIFEST["icons"]]
        self.assertEqual(sum("any" in p for p in purposes), 2)
        self.assertEqual(sum("maskable" in p for p in purposes), 1)
        self.assertEqual([p for p in purposes if len(p) > 1], [],
                         "no icon may double as any+maskable")
        self.assertEqual(urlsplit(MANIFEST["icons"][0]["src"]).path,
                         "/assets/icon-192.png")
        self.assertEqual(urlsplit(MANIFEST["icons"][1]["src"]).path,
                         "/assets/icon-512-any.png")
        self.assertEqual(urlsplit(MANIFEST["icons"][2]["src"]).path,
                         "/assets/icon-512.png")

    def test_icon_urls_are_cache_busted(self):
        for icon in MANIFEST["icons"]:
            with self.subTest(icon=icon["src"]):
                self.assertIn("v=", urlsplit(icon["src"]).query)

    def test_ios_gets_its_own_link(self):
        self.assertIn('rel="apple-touch-icon"', INDEX)

    def test_the_ios_icon_is_opaque(self):
        import re as _re
        m = _re.search(r'rel="apple-touch-icon"\s+href="([^"]+)"', INDEX)
        self.assertIsNotNone(m)
        path = PUBLIC / urlsplit(m.group(1)).path.lstrip("/")
        self.assertTrue(path.exists(), f"{m.group(1)} is missing")
        self.assertEqual(path.name, "icon-512.png",
                         "iOS composites the padded maskable square, not the "
                         "full-bleed splash mark")
        self.assertEqual(_transparent_pixel_count(path), 0,
                         "apple-touch-icon must have no transparent pixels")

    def test_the_maskable_icon_is_opaque(self):
        for icon in MANIFEST["icons"]:
            if "maskable" not in icon["purpose"].split():
                continue
            path = PUBLIC / urlsplit(icon["src"]).path.lstrip("/")
            with self.subTest(icon=icon["src"]):
                self.assertEqual(_transparent_pixel_count(path), 0,
                                 f"{icon['src']} must have no transparent pixels")

    def test_the_splash_matches_the_mark(self):
        import zlib
        from struct import unpack
        field = next(i for i in MANIFEST["icons"]
                     if i["sizes"] == "512x512" and "maskable" in i["purpose"].split())
        raw = (PUBLIC / urlsplit(field["src"]).path.lstrip("/")).read_bytes()
        w, h = unpack(">II", raw[16:24])
        idat = b"".join(
            raw[i + 8:i + 8 + unpack(">I", raw[i:i + 4])[0]]
            for i in _chunk_offsets(raw, b"IDAT")
        )
        line = zlib.decompress(idat)[:4]
        corner = "#%02x%02x%02x" % (line[1], line[2], line[3])
        self.assertEqual(MANIFEST["background_color"].lower(), corner,
                         f"splash {MANIFEST['background_color']} does not match "
                         f"the icon's own field {corner}")


class NothingIsCached(unittest.TestCase):

    def test_no_service_worker_is_registered(self):
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
        self.assertIn('media="(prefers-color-scheme: light)"', INDEX)
        self.assertIn('media="(prefers-color-scheme: dark)"', INDEX)


if __name__ == "__main__":
    unittest.main(verbosity=2)
