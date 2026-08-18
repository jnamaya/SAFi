"""
Governed-answer document export (backlog 66).

The contract, pinned here:

- render() produces a real DOCX (a ZIP, magic PK\\x03\\x04) and a real PDF
  (magic %PDF) from markdown answer text.
- The transparency footer is present in both formats.
- Format and input validation reject empty text, oversized text, and unknown
  formats, so the endpoint returns 400 rather than 500.

Pure unit test: no DB, no network. It only needs python-docx, markdown, and
xhtml2pdf, which the image installs from requirements.txt.
"""
import io
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.services import document_export as de

SAMPLE = """# Quarterly Summary

This is a **bold** claim and an *italic* aside with `inline code`.

## Findings

- First point
- Second point with a [link](https://example.com)

1. Step one
2. Step two

> A quoted line.

```
code block line 1
code block line 2
```

| Name | Value |
|------|-------|
| Alpha | 1 |
| Beta | 2 |
"""


class DocxExport(unittest.TestCase):

    def test_produces_a_valid_docx(self):
        content, mimetype, ext = de.render(SAMPLE, "Quarterly Summary", "docx", "Fiduciary")
        self.assertEqual(ext, "docx")
        self.assertIn("wordprocessingml", mimetype)
        self.assertTrue(content.startswith(b"PK\x03\x04"), "not a ZIP/DOCX container")
        # The DOCX is a zip; document.xml must carry the body text and footer.
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        self.assertIn("Quarterly Summary", xml)
        self.assertIn("First point", xml)
        self.assertIn("exported from SAFi", xml, "transparency footer missing")

    def test_footer_names_the_agent(self):
        content, _, _ = de.render(SAMPLE, "T", "docx", "Fiduciary")
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        self.assertIn("Fiduciary", xml)


class PdfExport(unittest.TestCase):

    def test_produces_a_valid_pdf(self):
        content, mimetype, ext = de.render(SAMPLE, "Quarterly Summary", "pdf", None)
        self.assertEqual(ext, "pdf")
        self.assertEqual(mimetype, "application/pdf")
        self.assertTrue(content.startswith(b"%PDF"), "not a PDF")
        self.assertGreater(len(content), 800, "PDF suspiciously small")


class Validation(unittest.TestCase):

    def test_empty_text_rejected(self):
        with self.assertRaises(ValueError):
            de.render("   ", "T", "pdf")

    def test_unknown_format_rejected(self):
        with self.assertRaises(ValueError):
            de.render("hello", "T", "rtf")

    def test_oversized_text_rejected(self):
        with self.assertRaises(ValueError):
            de.render("x" * (de.MAX_EXPORT_CHARS + 1), "T", "pdf")

    def test_default_attribution_when_none(self):
        content, _, _ = de.render("hello world", "T", "docx", None)
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        self.assertIn("an AI agent", xml)


if __name__ == "__main__":
    unittest.main(verbosity=2)
