"""
Document text extraction service.

Extracts plain text from uploaded files (PDF, DOCX, TXT, MD, CSV)
so it can be injected as context into the user's prompt.
"""
import os
import csv
import io
import logging
from typing import Tuple

log = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'.txt', '.md', '.pdf', '.docx', '.csv'}


def allowed_file(filename: str) -> bool:
    """Checks if the file extension is in the allowed set."""
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def extract_text(file_storage, filename: str, max_chars: int = 50000) -> Tuple[str, int]:
    """
    Extracts text from an uploaded file.

    Args:
        file_storage: A file-like object (e.g., from Flask's request.files).
        filename: The original filename (used to detect format).
        max_chars: Maximum characters to return. Documents exceeding this
                   will be truncated with a notice.

    Returns:
        A tuple of (extracted_text, total_chars_before_truncation).
    """
    ext = os.path.splitext(filename)[1].lower()

    if ext in ('.txt', '.md'):
        text = file_storage.read().decode('utf-8', errors='replace')
    elif ext == '.csv':
        text = _extract_csv(file_storage)
    elif ext == '.pdf':
        text = _extract_pdf(file_storage)
    elif ext == '.docx':
        text = _extract_docx(file_storage)
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    total_chars = len(text)
    if total_chars > max_chars:
        text = text[:max_chars] + (
            f"\n\n[... Document truncated at {max_chars:,} characters. "
            f"Total: {total_chars:,} characters ...]"
        )

    return text, total_chars


def _extract_csv(file_storage) -> str:
    """Reads a CSV and formats it as a Markdown table."""
    content = file_storage.read().decode('utf-8', errors='replace')
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return ""

    header = rows[0]
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("| " + " | ".join(["---"] * len(header)) + " |")
    for row in rows[1:]:
        # Pad or truncate columns to match header length
        padded = row + [''] * (len(header) - len(row))
        lines.append("| " + " | ".join(padded[:len(header)]) + " |")
    return "\n".join(lines)


def _extract_pdf(file_storage) -> str:
    """Extracts text from a PDF using PyPDF2."""
    try:
        import PyPDF2
    except ImportError:
        raise ValueError(
            "PDF support requires PyPDF2. "
            "Install with: pip install PyPDF2"
        )

    reader = PyPDF2.PdfReader(file_storage)
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text()
        if text and text.strip():
            pages.append(f"--- Page {i + 1} ---\n{text.strip()}")

    if not pages:
        raise ValueError("Could not extract any text from this PDF. It may be image-based.")

    return "\n\n".join(pages)


def _extract_docx(file_storage) -> str:
    """Extracts text from a DOCX using python-docx."""
    try:
        from docx import Document
    except ImportError:
        raise ValueError(
            "DOCX support requires python-docx. "
            "Install with: pip install python-docx"
        )

    doc = Document(file_storage)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]

    if not paragraphs:
        raise ValueError("Could not extract any text from this DOCX file.")

    return "\n\n".join(paragraphs)
