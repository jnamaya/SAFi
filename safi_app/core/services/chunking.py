from __future__ import annotations

import re
from typing import List

MAX_CHUNK_CHARS = 2000


def chunk_markdown(text: str, max_chunk_chars: int = MAX_CHUNK_CHARS) -> List[str]:
    m = re.match(r"^---\n.*?\n---\n", text, re.S)
    if m:
        text = text[m.end():]
    sections = re.split(r"(?m)^(?=#{1,6}\s)", text)

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
    if carry:
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
    if re.search(r"(?m)^#{1,6}\s", text or ""):
        return chunk_markdown(text, max_chunk_chars)
    return chunk_plain_text(text, max_chunk_chars)
