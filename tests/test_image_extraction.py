import io
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from safi_app.config import Config
from safi_app.core.services import document_processor as D

DP = (ROOT / "safi_app" / "core" / "services" / "document_processor.py").read_text(encoding="utf-8")
INDEX = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
REQS = (ROOT / "requirements.txt").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.tiff', '.tif', '.webp', '.bmp'}


class TheImageBytesNeverLeave(unittest.TestCase):

    def test_extraction_returns_text_not_image_data(self):
        for token in ("image_url", "base64", "inline_data", "b64_json"):
            self.assertNotIn(token, DP,
                             f"{token} in the document processor suggests image bytes "
                             "are being forwarded somewhere")

    def test_the_reason_is_written_down_next_to_the_code(self):
        self.assertIn("Phase Zero", DP)
        self.assertIn("32z", DP, "point at the backlog item that holds the open question")


class AcceptedTypes(unittest.TestCase):

    def test_every_image_extension_is_allowed(self):
        for ext in IMAGE_EXTS:
            with self.subTest(ext=ext):
                self.assertTrue(D.allowed_file("scan" + ext))

    def test_the_config_list_matches_the_processor(self):
        self.assertEqual(set(Config.ALLOWED_UPLOAD_EXTENSIONS), D.ALLOWED_EXTENSIONS)

    def test_the_file_picker_offers_them(self):
        m = INDEX[INDEX.index('accept="'):]
        accept = m[len('accept="'):m.index('"', len('accept="'))]
        for ext in IMAGE_EXTS:
            with self.subTest(ext=ext):
                self.assertIn(ext, accept)

    def test_unsupported_types_are_still_refused(self):
        self.assertFalse(D.allowed_file("payload.exe"))
        self.assertFalse(D.allowed_file("movie.mp4"))
        self.assertFalse(D.allowed_file("archive.zip"))


class OcrDegradesGracefully(unittest.TestCase):

    def test_an_image_without_ocr_available_says_so_plainly(self):
        with patch.object(D, "_ocr_available", return_value=False):
            with self.assertRaises(ValueError) as cm:
                D.extract_text(io.BytesIO(b"not-really-a-png"), "shot.png")
        self.assertIn("OCR", str(cm.exception))
        self.assertIn("tesseract", str(cm.exception))

    def test_availability_requires_the_binary_not_just_the_wheel(self):
        block = DP[DP.index("def _ocr_available"):]
        block = block[:block.index("\ndef _ocr_image_bytes")]
        self.assertIn("get_tesseract_version", block)

    def test_an_unreadable_image_is_an_error_not_an_empty_document(self):
        with patch.object(D, "_ocr_available", return_value=True), \
             patch.object(D, "_ocr_image_bytes", return_value=""):
            with self.assertRaises(ValueError) as cm:
                D.extract_text(io.BytesIO(b"x"), "chart.png")
        self.assertIn("No readable text", str(cm.exception))

    def test_ocr_failures_return_empty_rather_than_propagating(self):
        block = DP[DP.index("def _ocr_image_bytes"):]
        block = block[:block.index("\ndef _ocr_pdf_page_images")]
        self.assertIn("return \"\"", block)
        self.assertIn("log.warning", block)


class TranscriptionIsLabelled(unittest.TestCase):

    def test_image_text_is_marked_as_an_ocr_transcription(self):
        with patch.object(D, "_ocr_available", return_value=True), \
             patch.object(D, "_ocr_image_bytes", return_value="Invoice total 4,210.00"):
            text, total = D.extract_text(io.BytesIO(b"x"), "invoice.png")
        self.assertIn("OCR TRANSCRIPTION", text)
        self.assertIn("invoice.png", text)
        self.assertIn("Invoice total 4,210.00", text)

    def test_the_label_warns_that_figures_may_be_misread(self):
        with patch.object(D, "_ocr_available", return_value=True), \
             patch.object(D, "_ocr_image_bytes", return_value="123"):
            text, _ = D.extract_text(io.BytesIO(b"x"), "n.png")
        self.assertIn("uncertain", text.lower())

    def test_the_character_cap_still_applies_to_images(self):
        with patch.object(D, "_ocr_available", return_value=True), \
             patch.object(D, "_ocr_image_bytes", return_value="z" * 200):
            text, total = D.extract_text(io.BytesIO(b"x"), "big.png", max_chars=100)
        self.assertIn("truncated at 100 characters", text)
        self.assertGreater(total, 100)


class ScannedPdfs(unittest.TestCase):

    class _Page:
        def __init__(self, text, images=()):
            self._text, self.images = text, list(images)

        def extract_text(self):
            return self._text

    class _Img:
        def __init__(self, data=b"img"):
            self.data = data

    def _reader(self, pages):
        class R:
            def __init__(self, _):
                self.pages = pages
        return R

    def test_a_page_with_no_text_layer_is_ocrd(self):
        pages = [self._Page("Typed page one"), self._Page("", [self._Img()])]
        with patch.dict(sys.modules, {"pypdf": type("m", (), {"PdfReader": self._reader(pages)})}), \
             patch.object(D, "_ocr_available", return_value=True), \
             patch.object(D, "_ocr_image_bytes", return_value="Scanned page two"):
            out = D._extract_pdf(io.BytesIO(b"x"))
        self.assertIn("Typed page one", out)
        self.assertIn("Scanned page two", out)

    def test_a_partly_scanned_pdf_declares_that_ocr_was_used(self):
        pages = [self._Page("Typed"), self._Page("", [self._Img()])]
        with patch.dict(sys.modules, {"pypdf": type("m", (), {"PdfReader": self._reader(pages)})}), \
             patch.object(D, "_ocr_available", return_value=True), \
             patch.object(D, "_ocr_image_bytes", return_value="Scanned"):
            out = D._extract_pdf(io.BytesIO(b"x"))
        self.assertIn("read by OCR", out)
        self.assertRegex(out, r"1 of 2 pages")

    def test_a_fully_typed_pdf_gets_no_ocr_note(self):
        pages = [self._Page("Page one text is long enough to clear the floor")]
        with patch.dict(sys.modules, {"pypdf": type("m", (), {"PdfReader": self._reader(pages)})}), \
             patch.object(D, "_ocr_available", return_value=True), \
             patch.object(D, "_ocr_image_bytes", return_value="SHOULD NOT BE CALLED"):
            out = D._extract_pdf(io.BytesIO(b"x"))
        self.assertNotIn("read by OCR", out)
        self.assertNotIn("SHOULD NOT BE CALLED", out)

    def test_a_scan_with_ocr_unavailable_still_raises_the_old_error(self):
        pages = [self._Page("", [self._Img()])]
        with patch.dict(sys.modules, {"pypdf": type("m", (), {"PdfReader": self._reader(pages)})}), \
             patch.object(D, "_ocr_available", return_value=False):
            with self.assertRaises(ValueError) as cm:
                D._extract_pdf(io.BytesIO(b"x"))
        self.assertIn("Could not extract any text", str(cm.exception))


class Packaging(unittest.TestCase):

    def test_both_python_halves_are_declared(self):
        self.assertRegex(REQS, r"(?m)^pytesseract>=")
        self.assertRegex(REQS, r"(?m)^Pillow>=")

    def test_the_binary_is_installed_in_the_runtime_stage(self):
        self.assertIn("tesseract-ocr", DOCKERFILE)
        self.assertIn("tesseract-ocr-eng", DOCKERFILE)
        from_positions = [m.start() for m in re.finditer(r"(?m)^FROM ", DOCKERFILE)]
        self.assertTrue(from_positions, "no FROM instruction in the Dockerfile")
        runtime = DOCKERFILE[from_positions[-1]:]
        self.assertIn("tesseract-ocr", runtime,
                      "the apt install must be in the runtime stage")

    def test_the_language_pack_is_explicit(self):
        self.assertIn("tesseract-ocr-eng", DOCKERFILE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
