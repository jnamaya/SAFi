"""Heading-aware chunking for markdown/plain-text sources.

MOVED HERE from rag/build_index_v2.py (2026-08-07) so the offline CLI builder
and the live KB indexer share ONE implementation. They must not diverge: a
corpus chunked one way at build time and another way on re-index would change
retrieval behaviour with no code change visible at the call site, and the two
bug fixes documented below were expensive enough to find once.

`rag/build_index_v2.py` imports this (it puts the repo root on sys.path first,
since it runs as a script). Keep this module dependency-free — stdlib only —
so importing it never drags config, database or model code into the CLI path.
"""
from __future__ import annotations

import re
from typing import List

# Chunking limit for the built-in markdown/text chunker.
MAX_CHUNK_CHARS = 2000


def chunk_markdown(text: str, max_chunk_chars: int = MAX_CHUNK_CHARS) -> List[str]:
    """Splits on markdown headings, then packs sections into chunks of at most
    `max_chunk_chars`, splitting oversized sections on blank lines.

    Two things this must NOT do, both of which it used to:

    1. Emit a chunk that is only a heading. Splitting at every heading means an
       `# H1` immediately followed by an `## H2` — the shape of every doc in
       rag/docs — produced a chunk containing nothing but the title. Those were
       11% of the index, and because a bare title is a pure topic statement it
       embeds as an near-perfect match for topic questions, so they outranked
       the prose and burned retrieval slots. A live turn retrieved five chunks,
       four of which were titles; the Conscience then correctly scored the
       answer -1 for being ungrounded, because the grounding never arrived.
       Heading-only sections are now carried forward onto the next section,
       which also gives that chunk its parent heading as context.

    2. Index the YAML frontmatter. It was another 28 chunks of title/slug/tags,
       duplicating the H1 and carrying no prose.
    """
    m = re.match(r"^---\n.*?\n---\n", text, re.S)   # drop YAML frontmatter
    if m:
        text = text[m.end():]
    sections = re.split(r"(?m)^(?=#{1,6}\s)", text)

    # Carry heading-only sections onto the following one.
    merged: List[str] = []
    carry = ""
    for section in sections:
        section = section.strip()
        if not section:
            continue
        body = re.sub(r"^#{1,6}\s.*$", "", section, flags=re.M).strip()
        if not body:
            carry = f"{carry}\n\n{section}" if carry else section
            continue
        merged.append(f"{carry}\n\n{section}" if carry else section)
        carry = ""
    if carry:                     # trailing heading with nothing under it
        merged.append(carry)

    chunks: List[str] = []
    for section in merged:
        section = section.strip()
        if not section:
            continue
        if len(section) <= max_chunk_chars:
            chunks.append(section)
            continue
        current = ""
        for para in re.split(r"\n\s*\n", section):
            if current and len(current) + len(para) + 2 > max_chunk_chars:
                chunks.append(current.strip())
                current = para
            else:
                current = f"{current}\n\n{para}" if current else para
        if current.strip():
            chunks.append(current.strip())
    return chunks


def chunk_plain_text(text: str, max_chunk_chars: int = MAX_CHUNK_CHARS) -> List[str]:
    """Paragraph packing for text with no heading structure.

    Extracted PDF/DOCX/XLSX/CSV text usually has no `#` headings at all, so
    chunk_markdown() would return it as one enormous section and then split it
    on blank lines anyway. This is that path made explicit, and it guarantees
    forward progress on pathological input: a single paragraph longer than the
    limit (a PDF table flattened into one line, a CSV row with no wrapping) is
    hard-split rather than emitted as one oversized chunk that would blow the
    embedding window.
    """
    chunks: List[str] = []
    current = ""
    for para in re.split(r"\n\s*\n", text or ""):
        para = para.strip()
        if not para:
            continue
        while len(para) > max_chunk_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.append(para[:max_chunk_chars])
            para = para[max_chunk_chars:]
        if current and len(current) + len(para) + 2 > max_chunk_chars:
            chunks.append(current.strip())
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current.strip():
        chunks.append(current.strip())
    return chunks


def chunk_document(text: str, filename: str = "",
                   max_chunk_chars: int = MAX_CHUNK_CHARS) -> List[str]:
    """Picks a chunker from the content, not the extension.

    Extension is the wrong signal here: document_processor renders CSV and
    XLSX as markdown tables, and a .txt file may well carry `#` headings.
    Heading count decides.
    """
    if re.search(r"(?m)^#{1,6}\s", text or ""):
        return chunk_markdown(text, max_chunk_chars)
    return chunk_plain_text(text, max_chunk_chars)
