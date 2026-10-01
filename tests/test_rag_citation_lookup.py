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
# Luke 9's real chunk boundaries, which the lectionary reading rides on.
LUKE_9 = ([_chunk("Luke", 9, s, s + 3) for s in range(1, 56, 3)]
          + [_chunk("Luke", 9, 55, 59), _chunk("Luke", 9, 58, 62), _chunk("Luke", 9, 61, 62)])


def _covered_verses(retriever, query):
    """Every verse number the returned chunks actually contain."""
    verses = set()
    for i in retriever._keyword_search(query):
        md = retriever.metadata[i]["metadata"]
        verses.update(range(md["start_verse"], md["end_verse"] + 1))
    return verses


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


class AVerseRangeIsTheWholeRange(unittest.TestCase):
    """A lectionary reading is a RANGE, and the first verse is not the range.

    Reading only the leading verse of "Luke 9:57-62" returned the single chunk
    holding verse 57 (verses 55-59). Verses 60-62 were then absent from the
    audit material, the Intellect completed them from memory, and Textual
    Fidelity scored 0 for exactly that reason — a gap the retrieval created.
    """

    def test_the_tail_of_the_range_is_retrieved(self):
        r = _retriever(LUKE_9)
        covered = _covered_verses(r, "Luke 9:57-62")
        for verse in (57, 58, 59, 60, 61, 62):
            self.assertIn(verse, covered,
                          f"verse {verse} of the requested reading is missing")

    def test_every_verse_of_the_range_is_covered_without_gaps(self):
        r = _retriever(LUKE_9)
        covered = _covered_verses(r, "Luke 9:57-62")
        self.assertEqual(set(range(57, 63)) - covered, set(),
                         "the requested span must arrive unbroken")

    def test_the_preceding_chunks_of_the_chapter_are_not_dragged_in(self):
        r = _retriever(LUKE_9)
        covered = _covered_verses(r, "Luke 9:57-62")
        self.assertNotIn(1, covered, "the chapter opening is not part of the reading")
        self.assertNotIn(54, covered)

    def test_an_en_dash_range_is_the_same_range(self):
        r = _retriever(LUKE_9)
        self.assertEqual(r._keyword_search("Luke 9:57–62"),
                         r._keyword_search("Luke 9:57-62"))

    def test_a_single_verse_is_still_one_chunk(self):
        r = _retriever(LUKE_9)
        covered = _covered_verses(r, "Luke 9:57")
        self.assertTrue(57 in covered)
        self.assertNotIn(62, covered, "one verse must not pull in the range around it")

    def test_a_disjoint_list_spans_its_own_extremes(self):
        r = _retriever(PSALM_119)
        covered = _covered_verses(r, "Psalm 119:10, 20-25")
        self.assertIn(10, covered)
        self.assertIn(25, covered)


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
