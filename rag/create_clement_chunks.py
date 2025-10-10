#!/usr/bin/env python3
"""
create_clement_chunks.py (auto-detect verses v2)

Outputs chunks like:
{
  "text_chunk": "Citation: Chapter 3, verses 1 to 4\n(1) ... (2) ... (3) ... (4) ...",
  "metadata": {"source": "archive.org", "translation": "unknown"}
}

This version is aggressive about detecting verse markers. It tries many patterns,
including line-start numbers like "1 text", "1. text", "1) text", bracketed
forms [1], (1), <1>, and even Unicode superscripts ¹²³ embedded in text.

Run
  python3 create_clement_chunks.py \
    --input clement.txt \
    --output clement_chunks.json \
    --source archive.org \
    --translation unknown \
    --window-size 4 \
    --overlap 1

If it still finds 0, it prints diagnostics and falls back to per-chapter paragraph chunks
so you never end up with an empty file.
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
import unicodedata
from typing import Dict, List, Tuple, Optional

# Chapter patterns to try
CHAPTER_PATTERNS = [
    r"^\s*(?:CHAPTER|Chapter|Ch\.)\s+([IVXLCDM]+|\d+)\s*$",
    r"^\s*(?:LETTER|Letter)\s+([IVXLCDM]+|\d+)\s*$",
    r"^\s*(?:EPISTLE|Epistle)\s+([IVXLCDM]+|\d+)\s*$",
]

# Verse patterns to try, each must have exactly one capture group for the number
VERSE_PATTERNS = [
    r"\(\s*(\d+)\s*\)",                # (1)
    r"\[\s*(\d+)\s*\]",                # [1]
    r"<\s*(\d+)\s*>",                    # <1>
    r"(?m)^\s*(\d+)\s+[A-Za-z]",        # 1 text  (line start, space, letter)
    r"(?m)^\s*(\d+)\s*[\.)]\s+",       # 1. text or 1) text
    r"(?m)^\s*(\d+)\b",                  # 1  ...  (very loose line-start)
    # Inline loose: number followed by space then letter
    r"(?<!\d)(\d+)\s+[A-Za-z]",
]

# Unicode superscripts mapping
SUP_MAP = {
    "¹": "1", "²": "2", "³": "3", "⁰": "0", "⁴": "4", "⁵": "5", "⁶": "6",
    "⁷": "7", "⁸": "8", "⁹": "9",
}
SUP_CLASS = "[\u00B9\u00B2\u00B3\u2070-\u2079]+"  # ¹²³⁰…
SUPER_PATTERNS = [
    rf"(?m)^\s*({SUP_CLASS})\s+[A-Za-z]",      # line-start superscripts
    rf"(?<!\d)({SUP_CLASS})\s+[A-Za-z]",       # inline superscripts
]

ROMAN = {"I":1, "V":5, "X":10, "L":50, "C":100, "D":500, "M":1000}

def roman_to_int(s: str) -> Optional[int]:
    s = s.upper().strip()
    if not s or any(ch not in ROMAN for ch in s):
        return None
    total, prev = 0, 0
    for ch in reversed(s):
        val = ROMAN[ch]
        if val < prev:
            total -= val
        else:
            total += val
            prev = val
    return total if total > 0 else None


def normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("（", "(").replace("）", ")")
    s = s.replace("［", "[").replace("］", "]")
    return s

# ------------- chapter split -------------

def split_into_chapters(raw: str, user_chapter_pat: Optional[str]) -> List[Tuple[str, str]]:
    pats = [user_chapter_pat] if user_chapter_pat else CHAPTER_PATTERNS
    for pat in pats:
        cp = re.compile(pat, flags=re.MULTILINE)
        parts = cp.split(raw)
        if len(parts) > 1:
            chunks: List[Tuple[str, str]] = []
            preface = parts[0].strip()
            if preface:
                chunks.append(("Chapter 1", preface))
            for i in range(1, len(parts), 2):
                chap_id = parts[i].strip()
                body = parts[i + 1] if i + 1 < len(parts) else ""
                n = int(chap_id) if chap_id.isdigit() else (roman_to_int(chap_id) or chap_id)
                label = f"Chapter {n}"
                chunks.append((label, body))
            print(f"Chapters detected with pattern: {pat}\n  count={len(chunks)}")
            return chunks
    print("No chapter headers detected. Treating entire file as 'Chapter 1'.")
    return [("Chapter 1", raw)]

# ------------- verse extraction -------------

def choose_pattern(chapter_text: str, user_pat: Optional[str]) -> Tuple[str, int, bool]:
    # returns (pattern, hits, is_superscript)
    if user_pat:
        hits = len(re.findall(user_pat, chapter_text, flags=re.MULTILINE))
        return user_pat, hits, False

    # try normal patterns
    best_pat, best_hits = VERSE_PATTERNS[0], 0
    for pat in VERSE_PATTERNS:
        hits = len(re.findall(pat, chapter_text, flags=re.MULTILINE))
        if hits > best_hits:
            best_hits, best_pat = hits, pat
    if best_hits > 0:
        return best_pat, best_hits, False

    # try superscripts by normalizing them into digits for matching
    # we do this by replacing superscripts with placeholders so the same patterns work
    for spat in SUPER_PATTERNS:
        hits = len(re.findall(spat, chapter_text, flags=re.MULTILINE))
        if hits > 0:
            return spat, hits, True
    return VERSE_PATTERNS[0], 0, False


def to_ascii_superscripts(text: str) -> str:
    return "".join(SUP_MAP.get(ch, ch) for ch in text)


def extract_verses(chapter_text: str, verse_pat: str, superscript: bool) -> List[Tuple[int, str]]:
    text = chapter_text
    if superscript:
        text = to_ascii_superscripts(text)
    vp = re.compile(verse_pat, flags=re.MULTILINE)
    parts = vp.split(text)
    verses: List[Tuple[int, str]] = []

    # parts: [lead, num1, text1, num2, text2, ...]
    for i in range(1, len(parts), 2):
        raw_num = parts[i]
        # convert any leftover superscripts to digits
        raw_num = to_ascii_superscripts(raw_num)
        # strip trailing punctuation if any sneaks in
        raw_num = re.sub(r"\D+$", "", raw_num)
        if not raw_num:
            continue
        try:
            vnum = int(raw_num)
        except ValueError:
            continue
        text_after = parts[i + 1] if i + 1 < len(parts) else ""
        # collapse newlines and excess spaces
        text_after = re.sub(r"\s*\n\s*", " ", text_after).strip()
        verses.append((vnum, text_after))

    verses.sort(key=lambda x: x[0])
    return verses

# ------------- windowing -------------

def build_windows(verses: List[Tuple[int, str]], window_size: int, overlap: int) -> List[Tuple[int, int, str]]:
    if not verses:
        return []
    if window_size <= 0:
        window_size = 4
    if overlap < 0 or overlap >= window_size:
        overlap = 0
    step = window_size - overlap

    windows: List[Tuple[int, int, str]] = []
    for start in range(0, len(verses), step):
        end = min(start + window_size, len(verses))
        if start >= end:
            break
        slice_ = verses[start:end]
        sv, ev = slice_[0][0], slice_[-1][0]
        # rebuild with visible markers (n)
        text = " ".join([f"({v}) {t}".strip() for v, t in slice_])
        windows.append((sv, ev, text))
        if end == len(verses):
            break
    return windows

# ------------- paragraph fallback -------------

def para_fallback(chapter_body: str, window_size: int, overlap: int) -> List[Tuple[int, int, str]]:
    # split by blank lines into paragraphs, then window
    paras = [p.strip() for p in re.split(r"\n\s*\n+", chapter_body) if p.strip()]
    verses = [(i + 1, re.sub(r"\s*\n\s*", " ", p)) for i, p in enumerate(paras)]
    return build_windows(verses, window_size, overlap)

# ------------- main -------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", "-i", required=True)
    ap.add_argument("--output", "-o", required=True)
    ap.add_argument("--source", default="archive.org")
    ap.add_argument("--translation", default="unknown")
    ap.add_argument("--chapter-pattern", default=None)
    ap.add_argument("--verse-pattern", default=None)
    ap.add_argument("--window-size", type=int, default=4)
    ap.add_argument("--overlap", type=int, default=1)
    args = ap.parse_args()

    raw = Path(args.input).read_text(encoding="utf-8", errors="ignore")
    raw = normalize_text(raw)

    chapters = split_into_chapters(raw, args.chapter_pattern)
    print(f"Total chapters considered: {len(chapters)}")

    out: List[Dict] = []
    total = 0

    for idx, (label, body) in enumerate(chapters, 1):
        pat, hits, is_sup = choose_pattern(body, args.verse_pattern)
        print(f"Chapter {idx} '{label}': verse-pattern='{pat}' hits={hits} superscript={is_sup}")

        verses = extract_verses(body, pat, is_sup)
        if not verses:
            print("  No verses extracted, using paragraph fallback for this chapter.")
            windows = para_fallback(body, args.window_size, args.overlap)
        else:
            windows = build_windows(verses, args.window_size, args.overlap)
        print(f"  Windows built: {len(windows)}")

        m = re.search(r"(\d+)$", label)
        chap_num = m.group(1) if m else label
        for sv, ev, text in windows:
            out.append({
                "text_chunk": f"Citation: Chapter {chap_num}, verses {sv} to {ev}\n" + text,
                "metadata": {"source": args.source, "translation": args.translation}
            })
        total += len(windows)

    Path(args.output).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {total} chunks to {args.output}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
