"""
The Intellect must not emit TeX markup.

WHY. Switching the demo's default Intellect to `gpt-5.6-luna` made this visible
overnight. Measured before fixing: **0 of 187** stored assistant messages
contained math markup (they were produced by gemini-3.5-flash-lite / gpt-oss),
but **4 of 4** math-adjacent questions to Luna emitted TeX. Frontier models reach
for LaTeX where the older lite models did not.

It is not a tutor-only concern. "Explain compound interest" and "How is the
Sharpe ratio calculated" are Fiduciary questions, and SAFI_PROFILE=fiduciary is
the demo's default agent.

What the user saw: `marked` strips the backslash off `\\(` and `\\[` but leaves
the macros, so

    in:  The Sharpe ratio is \\( \\frac{R_p - R_f}{\\sigma_p} \\)
    out: <p>The Sharpe ratio is ( \\frac{R_p - R_f}{\\sigma_p} )</p>

The fix is a prompt clause rather than a KaTeX dependency: measured 4/4 clean
with readable output, and it covers every model, the WordPress widget and the
mobile shell for free. See backlog item 19 for why KaTeX was deferred.

Two failure modes this pins, both silent:

1. **The clause getting dropped or reworded past usefulness** during an unrelated
   prompt edit. `system_prompts.json` is one long single-line JSON string, which
   makes accidental damage easy and invisible in review.
2. **A brace sneaking into the clause.** `formatting_instructions` is passed
   through `str.format(agent_style_rules=...)` (`intellect.py:186`), so a
   single `{` or `}` raises at request time and takes down every Intellect call.
   A TeX example like `\\frac{a}{b}` in the clause would do exactly that — which
   is why the clause names bare commands and carries no braces.

Requires no database and makes no network calls. Run:
    venv/bin/python tests/test_math_formatting.py
"""
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
        """A prohibition with no replacement just produces prose-only answers."""
        low = self.fi.lower()
        for token in ("latex", "tex markup"):
            with self.subTest(token=token):
                self.assertIn(token, low)
        # must name the delimiters that actually appear in output. Luna emits
        # \( \) and \[ \] far more than $, which is the opposite of what the
        # original bug report assumed.
        for delim in (r"\(", r"\[", "$$"):
            with self.subTest(delimiter=delim):
                self.assertIn(delim, self.fi,
                              f"the clause must name {delim} — it is a delimiter "
                              f"models actually use")
        self.assertTrue(re.search(r"plain|Unicode", self.fi),
                        "the clause must say what to write instead of TeX")

    def test_03_clause_survives_str_format(self):
        """The regression that would break EVERY Intellect call, not just math
        ones. intellect.py calls .format(agent_style_rules=style) on this
        string, so one stray brace is a hard failure at request time."""
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
        """Belt and braces on test_03: locate the clause and assert it is
        brace-free, so the failure is reported against the clause rather than
        against the whole string."""
        start = self.fi.find("MATHEMATICS")
        # find(), not index(): a missing clause is test_01's job to report, and
        # this one should fail readably rather than raise ValueError.
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
        """The Fiduciary talks about money constantly. Telling a model to avoid
        '$' without qualification invites it to mangle '$500 per month'."""
        self.assertIn("currency", self.fi.lower(),
                      "the clause must exempt currency, or banning '$' will make "
                      "the Fiduciary write amounts oddly")

    def test_06_the_reflection_contract_is_untouched(self):
        """The clause was inserted next to the delimiter instruction. If it
        displaced any of that, reflections stop parsing and the audit record
        silently loses the Intellect's stated reasoning."""
        self.assertIn("---REFLECTION---", self.fi)
        self.assertIn('"reflection"', self.fi)
        self.assertIn("{{", self.fi,
                      "the escaped example JSON braces are gone — the example "
                      "must stay double-braced to survive .format()")
        # clause must come BEFORE the delimiter instruction: it governs the
        # answer body, not the reflection JSON.
        pos = self.fi.find("MATHEMATICS")
        self.assertNotEqual(pos, -1, "no MATHEMATICS clause to place (see test_01)")
        self.assertLess(pos, self.fi.index("---REFLECTION---"),
                        "the clause governs the answer body, so it must precede the "
                        "reflection instruction")

    def test_07_no_other_prompt_reintroduces_tex(self):
        """Nothing else in the prompt file should instruct or exemplify TeX."""
        blob = json.dumps(self.doc)
        for bad in (r"\\frac", r"\\begin{equation}", "$$x"):
            with self.subTest(pattern=bad):
                # the MATHEMATICS clause names \frac in order to forbid it, so
                # count occurrences instead of asserting outright absence.
                if bad == r"\\frac":
                    self.assertLessEqual(
                        blob.count(bad), 1,
                        "\\frac appears more than once — it should occur only in "
                        "the prohibition")
                else:
                    self.assertNotIn(bad, blob)


if __name__ == "__main__":
    unittest.main(verbosity=2)
