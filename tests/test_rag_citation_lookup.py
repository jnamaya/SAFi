"""A citation must return the passage that was asked for.

`Retriever._keyword_search` matches a book and chapter, and the chunks it
compares against span ~4 overlapping verses. Slicing that result by k answers
with the OPENING of the chapter: at k=50 "Psalm 119" lost verses 148-176, and
at k=5 "Psalm 119:105" answered from verses 1-20 and never reached verse 105.
So a verse in the query now narrows the match, and a chapter-wide request
returns the chapter whole.

The search half is stubbed — this exercises the matching and the bound, not
the vector index.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.services.retriever import Retriever


def _chunk(book, chapter, start, end, text=""):
    return {"text_chunk": text or f"{book} {chapter}:{start}-{end}",
            "metadata": {"source": "bible", "book": book, "chapter": chapter,
                         "start_verse": start, "end_verse": end}}


def _retriever(metadata):
    """A Retriever with only what _keyword_search reads: metadata and log."""
    r = Retriever.__new__(Retriever)
    r.kb_name = "bible_bsb_v1"
    r.metadata = metadata
    import logging
    r.log = logging.getLogger("test_citation")
    return r


# Psalm 119 has 176 verses; the real index chunks it into 59 overlapping pieces.
PSALM_119 = [_chunk("Psalm", 119, s, min(s + 3, 176)) for s in range(1, 177, 3)]
JOHN_3 = [_chunk("John", 3, s, s + 3) for s in range(1, 37, 3)]


class AVerseNarrowsTheChapter(unittest.TestCase):

    def test_a_verse_reaches_the_verse_and_not_the_opening(self):
        r = _retriever(PSALM_119)
        spans = [(r.metadata[i]["metadata"]["start_verse"],
                  r.metadata[i]["metadata"]["end_verse"])
                 for i in r._keyword_search("Psalm 119:105")]
        self.assertTrue(any(s <= 105 <= e for s, e in spans))
        self.assertEqual(len(spans), 1, "one 5-verse chunk should cover verse 105")

    def test_the_chapter_opening_is_not_what_answers(self):
        r = _retriever(PSALM_119)
        verses = [r.metadata[i]["metadata"]["start_verse"]
                  for i in r._keyword_search("Psalm 119:105")]
        self.assertNotIn(1, verses,
                         "a k-slice would return verse 1 and never verse 105")

    def test_overlapping_chunks_that_span_the_verse_are_all_kept(self):
        r = _retriever(JOHN_3)
        spans = [(r.metadata[i]["metadata"]["start_verse"],
                  r.metadata[i]["metadata"]["end_verse"])
                 for i in r._keyword_search("John 3:16")]
        self.assertTrue(any(s <= 16 <= e for s, e in spans))
        self.assertLess(len(spans), len(JOHN_3), "the chapter should not come back whole")

    def test_a_verse_number_is_not_mistaken_for_a_second_citation(self):
        # "John 3:16" is one citation; the 16 must not be read as a chapter.
        r = _retriever(JOHN_3 + [_chunk("John", 16, 1, 4)])
        for i in r._keyword_search("John 3:16"):
            meta = r.metadata[i]["metadata"]
            self.assertEqual(meta["book"], "John")
            self.assertEqual(meta["chapter"], 3)


class AChapterCitationIsNotTrimmed(unittest.TestCase):

    def test_the_whole_longest_chapter_arrives(self):
        r = _retriever(PSALM_119)
        matched = r._keyword_search("Psalm 119")
        self.assertEqual(len(matched), len(PSALM_119),
                         "the longest chapter in the Bible must not be sliced")

    def test_indices_come_back_in_reading_order(self):
        r = _retriever(PSALM_119)
        self.assertEqual(r._keyword_search("Psalm 119"), sorted(r._keyword_search("Psalm 119")))

    def test_k_is_a_backstop_not_a_citation_bound(self):
        r = _retriever(PSALM_119)
        self.assertEqual(len(r._keyword_search("Psalm 119", k=5)), 5,
                         "a caller that explicitly wants a bound still gets one")


class NonCitationsAndOddInput(unittest.TestCase):

    def test_no_citation_matches_nothing(self):
        self.assertEqual(_retriever(PSALM_119)._keyword_search("what is love?"), [])

    def test_an_unknown_book_matches_nothing(self):
        self.assertEqual(_retriever(PSALM_119)._keyword_search("Ecclesiasticus 3:1"), [])

    def test_chunks_without_verse_metadata_are_kept_not_dropped(self):
        # A flat-shaped corpus cannot be placed against a verse, so the chapter
        # comes back whole rather than leaving a gap the model cannot see.
        flat = [{"text_chunk": "John 3:16 text",
                 "metadata": {"book": "John", "chapter": 3}}]
        r = _retriever(flat)
        self.assertEqual(len(r._keyword_search("John 3:16")), 1)


if __name__ == "__main__":
    unittest.main()
