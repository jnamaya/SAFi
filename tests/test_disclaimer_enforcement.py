"""
The mandatory disclaimer is enforced by the Will, deterministically, and is NOT
adjudicated by the Conscience.

WHY. Both requirements used to be expressed twice: the Will checks
`mandatory_disclaimer_substring` against the draft (a substring test), and the
value rubrics ALSO told the Conscience to score disclaimer presence. Asking a
model to judge string equality produced exactly the failure you would expect —
the same byte-identical disclaimer scored +1 on one turn and -1 at 0.95
confidence on the next, with the invented reason "not verbatim". The Fiduciary's
Transparency (weight 0.25) and the Health Navigator's Patient Safety (weight
0.40) were both affected, which is why it was noticeable in normal use.

These tests pin both halves: the deterministic gate still blocks a draft that
omits the disclaimer, and no rubric asks a model to re-judge it.

Requires no database. Run:  venv/bin/python tests/test_disclaimer_enforcement.py
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.personas.fiduciary import THE_FIDUCIARY_PERSONA
from safi_app.core.personas.health_navigator import THE_HEALTH_NAVIGATOR_PERSONA

# Personas that arm the Will's disclaimer gate. If a new one does, add it here —
# the point of this file is that arming the gate and scoring it are mutually
# exclusive.
DISCLAIMER_PERSONAS = {
    "fiduciary": THE_FIDUCIARY_PERSONA,
    "health_navigator": THE_HEALTH_NAVIGATOR_PERSONA,
}


def _structural(persona):
    # Key name must match will.py:88 — `structural_requirements`, not
    # `structural`. Getting this wrong makes every assertion below vacuously
    # pass against an empty dict, which is how a test file like this ends up
    # guarding nothing.
    rules = persona.get("will_rules") or {}
    return rules.get("structural_requirements") or {}


class TestWillOwnsTheDisclaimer(unittest.TestCase):
    """The deterministic half: the gate is armed and its substring is real."""

    def test_01_gate_is_armed_with_a_usable_substring(self):
        for name, persona in DISCLAIMER_PERSONAS.items():
            with self.subTest(persona=name):
                st = _structural(persona)
                self.assertTrue(st.get("require_disclaimer"),
                                f"{name}: require_disclaimer must stay on — it is the ONLY "
                                f"enforcement now that the rubric no longer scores it")
                sub = (st.get("mandatory_disclaimer_substring") or "").strip()
                self.assertTrue(sub, f"{name}: require_disclaimer with an empty substring "
                                     f"makes will.py skip the check entirely")
                self.assertGreater(len(sub), 20,
                                   f"{name}: substring too short to be a meaningful match")

    def test_02_the_substring_appears_in_the_style_instruction(self):
        """The Intellect is told to emit the disclaimer; the Will checks for it.
        If those two texts drift, every draft gets blocked."""
        for name, persona in DISCLAIMER_PERSONAS.items():
            with self.subTest(persona=name):
                sub = _structural(persona)["mandatory_disclaimer_substring"].strip()
                style = persona.get("style") or ""
                self.assertIn(sub, style,
                              f"{name}: the Will's required substring does not appear in the "
                              f"style text, so the model is never told to write what the gate "
                              f"demands")


class TestConscienceDoesNotReAdjudicate(unittest.TestCase):
    """The half that regressed. A rubric mentioning the disclaimer invites a
    model to judge wording, which is what produced the false -1."""

    def _rubric_prose(self, persona):
        chunks = []
        for v in persona.get("values") or []:
            r = v.get("rubric") or {}
            chunks.append((v.get("value"), r.get("description") or ""))
            for g in r.get("scoring_guide") or []:
                chunks.append((v.get("value"), g.get("descriptor") or ""))
        return chunks

    def test_03_no_rubric_mentions_the_disclaimer(self):
        for name, persona in DISCLAIMER_PERSONAS.items():
            for value, text in self._rubric_prose(persona):
                with self.subTest(persona=name, value=value):
                    self.assertNotIn("disclaimer", text.lower(),
                                     f"{name}/{value}: rubric text asks the Conscience to judge "
                                     f"the disclaimer, which the Will already checks "
                                     f"deterministically. Presence is not a matter of opinion.")

    def test_04_no_persona_anywhere_scores_the_disclaimer(self):
        """Widened past the two known agents: any persona arming the gate must
        not also score it, and any persona scoring it must be caught here."""
        import safi_app.core.personas as pkg
        import importlib, pkgutil
        offenders = []
        for mod in pkgutil.iter_modules(pkg.__path__):
            m = importlib.import_module(f"{pkg.__name__}.{mod.name}")
            for attr in dir(m):
                obj = getattr(m, attr)
                if not isinstance(obj, dict) or "values" not in obj:
                    continue
                for v in obj.get("values") or []:
                    if "disclaimer" in json.dumps(v.get("rubric") or {}).lower():
                        offenders.append(f"{mod.name}:{v.get('value')}")
        self.assertEqual(offenders, [], f"rubrics scoring the disclaimer: {offenders}")

    def test_05_the_values_still_score_something(self):
        """Removing the clause must not hollow out the value. Each affected
        rubric needs a full -1/0/+1 guide describing a real judgement."""
        for name, persona in DISCLAIMER_PERSONAS.items():
            for v in persona.get("values") or []:
                with self.subTest(persona=name, value=v.get("value")):
                    guide = (v.get("rubric") or {}).get("scoring_guide") or []
                    scores = sorted(g.get("score") for g in guide)
                    self.assertEqual(scores, [-1.0, 0.0, 1.0],
                                     f"{name}/{v.get('value')}: expected a -1/0/+1 guide")
                    for g in guide:
                        self.assertGreater(len(g.get("descriptor") or ""), 20,
                                           "descriptor too thin to score against")


if __name__ == "__main__":
    unittest.main(verbosity=2)
