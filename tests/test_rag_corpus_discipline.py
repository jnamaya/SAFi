"""
The RAG corpus must not contradict the project's message discipline.

WHY THIS EXISTS
---------------
`rag/docs/` is a third copy of the project's claims, alongside the website and the
repo docs, and it is the copy nobody reads. It is also the copy the Steward answers
FROM, so a retired term or an unsupportable claim in here is spoken to users as
fact. When it was audited on 2026-08-03 after a week of heavy editing it held three
defects, and it had come through mostly by luck: the "persona" references were
cleaned only because someone happened to be working nearby.

Nothing detected that drift. This does.

Each rule below corresponds to an entry in docs/internal/AUDIENCE_AND_MESSAGING.md.
Adding a rule here is cheap; the expensive thing is finding out from a user that the
Steward told them SAFi was "the first" of anything.

Run:  venv/bin/python tests/test_rag_corpus_discipline.py
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CORPUS = sorted((ROOT / "rag" / "docs").glob("*.md"))


def offenders(pattern, flags=re.I):
    """Every (file, line no, line) in the corpus matching pattern."""
    rx = re.compile(pattern, flags)
    out = []
    for f in CORPUS:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if rx.search(line):
                out.append((f.name, n, line.strip()))
    return out


def report(hits):
    return "\n".join(f"    {f}:{n}  {ln[:110]}" for f, n, ln in hits)


class TestCorpusExists(unittest.TestCase):

    def test_corpus_is_present_and_nonempty(self):
        # Guards against the rules below passing vacuously because a path changed.
        self.assertGreater(len(CORPUS), 15,
                           f"expected the SAFi knowledge base under rag/docs; found {len(CORPUS)}")
        for f in CORPUS:
            self.assertGreater(len(f.read_text(encoding="utf-8").split()), 20,
                               f"{f.name} is nearly empty — an empty chunk retrieves badly")


class TestRetiredVocabulary(unittest.TestCase):

    def test_no_persona(self):
        # Deprecated in favour of agent / profile / policy. "personal" and
        # "personality" are ordinary words and must not trip this.
        hits = [h for h in offenders(r"\bpersonas?\b")]
        self.assertEqual(hits, [], "'persona' is retired vocabulary:\n" + report(hits))

    def test_no_ethical_profile(self):
        hits = offenders(r"ethical\s+profiles?")
        self.assertEqual(hits, [],
                         "the thing is a POLICY; a profile is what the compiler "
                         "produces from charter + policy:\n" + report(hits))


class TestUnsupportableClaims(unittest.TestCase):

    def test_no_priority_claim(self):
        # "the first open-source ..." cannot be substantiated and the Steward
        # would assert it as fact.
        hits = offenders(r"\bthe first\b[^.]{0,40}\bopen[- ]source\b")
        self.assertEqual(hits, [], "unsupportable priority claim:\n" + report(hits))

    def test_no_certification_claim(self):
        # Readiness is not compliance. "certified"/"compliant with" overstate it.
        hits = offenders(r"\b(is|are)\s+(certified|compliant with)\b")
        self.assertEqual(hits, [],
                         "readiness is not certification:\n" + report(hits))

    def test_never_claims_to_prevent_hallucination(self):
        # Only a POSITIVE claim is a defect. "SAFi does not prevent hallucination"
        # is the correct statement and appears in two articles deliberately — the
        # first version of this rule failed on the very sentence it wanted.
        hits = [h for h in offenders(r"prevents?\s+hallucinat")
                if not re.search(r"\b(not|never|cannot|can't|won't|doesn't|does not)\b[^.]{0,30}$",
                                 h[2][:h[2].lower().find("prevent")], re.I)]
        self.assertEqual(hits, [],
                         "claims to PREVENT hallucination; grounding does that:\n" + report(hits))


class TestFacultyCounts(unittest.TestCase):

    def test_four_faculties_only_when_qualified_as_the_loop(self):
        # "four faculties" is correct ONLY when explicitly counting loop steps,
        # because Values is a faculty but not a step. Allow the line if it names
        # the loop; fail it otherwise.
        hits = [h for h in offenders(r"four\s+faculties")
                if not re.search(r"loop|step|stage|sequen|moving part|values",
                                 h[2], re.I)]
        self.assertEqual(hits, [],
                         "'four faculties' needs the loop qualifier — there are five:\n"
                         + report(hits))

    def test_four_principles_is_never_correct(self):
        # Unlike faculties, there is no reading where four principles is right:
        # Governed Action is the fifth.
        hits = offenders(r"four\s+principles")
        self.assertEqual(hits, [],
                         "there are five principles; Governed Action is the fifth:\n"
                         + report(hits))


class TestNoDeadInternalLinks(unittest.TestCase):

    def test_no_links_to_retired_articles(self):
        # Articles retired from the site. The Steward citing a 404 is worse than
        # citing nothing.
        retired = ["what-is-saf"]
        hits = []
        for slug in retired:
            hits += offenders(re.escape(slug))
        self.assertEqual(hits, [],
                         "links to a retired article:\n" + report(hits))

    def test_cross_references_point_at_existing_docs(self):
        # Several docs carry "- NN Title" indexes of their siblings. A reference to
        # a deleted doc sends the Steward looking for knowledge that is gone.
        numbers = {f.name.split("_", 1)[0] for f in CORPUS}
        hits = []
        for f in CORPUS:
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                m = re.match(r"^\s*-\s+(\d{2})\s+\S", line)
                if m and m.group(1) not in numbers:
                    hits.append((f.name, n, line.strip()))
        self.assertEqual(hits, [],
                         "cross-reference to a document that no longer exists:\n" + report(hits))


if __name__ == "__main__":
    unittest.main(verbosity=2)
