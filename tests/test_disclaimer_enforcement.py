import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.agents.fiduciary import THE_FIDUCIARY_AGENT
from safi_app.core.agents.health_navigator import THE_HEALTH_NAVIGATOR_AGENT

DISCLAIMER_AGENTS = {
    "fiduciary": THE_FIDUCIARY_AGENT,
    "health_navigator": THE_HEALTH_NAVIGATOR_AGENT,
}


def _structural(agent):
    rules = agent.get("will_rules") or {}
    return rules.get("structural_requirements") or {}


class TestWillOwnsTheDisclaimer(unittest.TestCase):

    def test_01_gate_is_armed_with_a_usable_substring(self):
        for name, agent in DISCLAIMER_AGENTS.items():
            with self.subTest(agent=name):
                st = _structural(agent)
                self.assertTrue(st.get("require_disclaimer"),
                                f"{name}: require_disclaimer must stay on — it is the ONLY "
                                f"enforcement now that the rubric no longer scores it")
                sub = (st.get("mandatory_disclaimer_substring") or "").strip()
                self.assertTrue(sub, f"{name}: require_disclaimer with an empty substring "
                                     f"makes will.py skip the check entirely")
                self.assertGreater(len(sub), 20,
                                   f"{name}: substring too short to be a meaningful match")

    def test_02_the_substring_appears_in_the_style_instruction(self):
        for name, agent in DISCLAIMER_AGENTS.items():
            with self.subTest(agent=name):
                sub = _structural(agent)["mandatory_disclaimer_substring"].strip()
                style = agent.get("style") or ""
                self.assertIn(sub, style,
                              f"{name}: the Will's required substring does not appear in the "
                              f"style text, so the model is never told to write what the gate "
                              f"demands")


class TestConscienceDoesNotReAdjudicate(unittest.TestCase):

    def _rubric_prose(self, agent):
        chunks = []
        for v in agent.get("values") or []:
            r = v.get("rubric") or {}
            chunks.append((v.get("value"), r.get("description") or ""))
            for g in r.get("scoring_guide") or []:
                chunks.append((v.get("value"), g.get("descriptor") or ""))
        return chunks

    def test_03_no_rubric_mentions_the_disclaimer(self):
        for name, agent in DISCLAIMER_AGENTS.items():
            for value, text in self._rubric_prose(agent):
                with self.subTest(agent=name, value=value):
                    self.assertNotIn("disclaimer", text.lower(),
                                     f"{name}/{value}: rubric text asks the Conscience to judge "
                                     f"the disclaimer, which the Will already checks "
                                     f"deterministically. Presence is not a matter of opinion.")

    def test_04_no_agent_anywhere_scores_the_disclaimer(self):
        import safi_app.core.agents as pkg
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
        for name, agent in DISCLAIMER_AGENTS.items():
            for v in agent.get("values") or []:
                with self.subTest(agent=name, value=v.get("value")):
                    guide = (v.get("rubric") or {}).get("scoring_guide") or []
                    scores = sorted(g.get("score") for g in guide)
                    self.assertEqual(scores, [-1.0, 0.0, 1.0],
                                     f"{name}/{v.get('value')}: expected a -1/0/+1 guide")
                    for g in guide:
                        self.assertGreater(len(g.get("descriptor") or ""), 20,
                                           "descriptor too thin to score against")


if __name__ == "__main__":
    unittest.main(verbosity=2)
