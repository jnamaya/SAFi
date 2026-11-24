import json
import re
import unittest
from pathlib import Path

PROMPTS = (Path(__file__).resolve().parent.parent
           / "safi_app" / "core" / "system_prompts.json")


class MathFormattingClause(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(PROMPTS.read_text(encoding="utf-8"))
        cls.fi = cls.doc["intellect_engine"]["formatting_instructions"]

    def test_01_clause_is_present(self):
        self.assertIn("MATHEMATICS", self.fi,
                      "the MATHEMATICS clause is gone — the Intellect will emit TeX "
                      "again and marked will render it as raw symbols")

    def test_02_it_forbids_tex_and_says_what_to_do_instead(self):
        low = self.fi.lower()
        for token in ("latex", "tex markup"):
            with self.subTest(token=token):
                self.assertIn(token, low)
        for delim in (r"\(", r"\[", "$$"):
            with self.subTest(delimiter=delim):
                self.assertIn(delim, self.fi,
                              f"the clause must name {delim} — it is a delimiter "
                              f"models actually use")
        self.assertTrue(re.search(r"plain|Unicode", self.fi),
                        "the clause must say what to write instead of TeX")

    def test_03_clause_survives_str_format(self):
        try:
            out = self.fi.format(agent_style_rules="STYLE RULES")
        except (KeyError, IndexError, ValueError) as exc:
            self.fail(f"formatting_instructions no longer survives .format(): "
                      f"{type(exc).__name__}: {exc}. A single unescaped brace does "
                      f"this — TeX examples must not include braces such as "
                      f"\\frac{{a}}{{b}}.")
        self.assertIn("STYLE RULES", out)
        self.assertIn("MATHEMATICS", out)

    def test_04_the_clause_itself_contains_no_tex_braces(self):
        start = self.fi.find("MATHEMATICS")
        self.assertNotEqual(start, -1, "no MATHEMATICS clause to check (see test_01)")
        end = self.fi.find("\n\n", start)
        clause = self.fi[start:end if end != -1 else len(self.fi)]
        for ch in "{}":
            with self.subTest(char=ch):
                self.assertNotIn(ch, clause,
                                 f"the MATHEMATICS clause contains {ch!r}; "
                                 f"formatting_instructions is str.format()ed, so "
                                 f"this breaks every Intellect call")

    def test_05_currency_is_explicitly_protected(self):
        self.assertIn("currency", self.fi.lower(),
                      "the clause must exempt currency, or banning '$' will make "
                      "the Fiduciary write amounts oddly")

    def test_06_the_reflection_contract_is_untouched(self):
        self.assertIn("---REFLECTION---", self.fi)
        self.assertIn('"reflection"', self.fi)
        self.assertIn("{{", self.fi,
                      "the escaped example JSON braces are gone — the example "
                      "must stay double-braced to survive .format()")
        pos = self.fi.find("MATHEMATICS")
        self.assertNotEqual(pos, -1, "no MATHEMATICS clause to place (see test_01)")
        self.assertLess(pos, self.fi.index("---REFLECTION---"),
                        "the clause governs the answer body, so it must precede the "
                        "reflection instruction")

    def test_07_no_other_prompt_reintroduces_tex(self):
        blob = json.dumps(self.doc)
        for bad in (r"\\frac", r"\\begin{equation}", "$$x"):
            with self.subTest(pattern=bad):
                if bad == r"\\frac":
                    self.assertLessEqual(
                        blob.count(bad), 1,
                        "\\frac appears more than once — it should occur only in "
                        "the prohibition")
                else:
                    self.assertNotIn(bad, blob)


if __name__ == "__main__":
    unittest.main(verbosity=2)
