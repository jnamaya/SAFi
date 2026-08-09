"""
Classifying a policy document: the normalization contract of pass 1.

WHY. Turning an organization's AI policy into SAFi governance is mostly an
exercise in REFUSING to convert things. Measured against a real 15-page
corporate AI Use Policy, roughly 11 pages carry no agent-constraining
content at all — committee membership, training obligations,
a 49-item intake questionnaire, disciplinary process. A model told to "extract
values" produces a rubric for each of them, and those rubrics then score the
wrong party while the agent looks misaligned. That failure has already happened
once here; see item 22 in the backlog.

So the server does not trust the model's routing blindly. This pins the
normalization that runs after it:

  * A "structural" clause with no literal text to check cannot be checked
    literally. It is DEMOTED to a scored value, not dropped — it is still a real
    obligation — and the reason says why.
  * Same for a "blacklist" clause with no phrase.
  * An unrecognized destination falls back to "none", the tier that enforces
    nothing. Guessing it into a tier that does enforce would turn a parse glitch
    into a blocking rule.
  * Definitions and notes survive normalization, because they carry the two
    findings that make the feature honest: enumerations sharpen rubrics, and a
    document that only REFERENCES the org's mission cannot populate it.

These are pure-function assertions over the endpoint's normalization step, so
they need no model, no database and no network.

Run:  venv/bin/python tests/test_document_classification.py
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.api import policy_api_routes as pr


def normalize(parsed):
    """Mirror of the endpoint's post-parse normalization.

    Kept in the test rather than imported because the endpoint inlines it inside
    an async Flask view; the assertions below are about the CONTRACT, and the
    source-shape guard at the bottom fails if the two drift apart.
    """
    buckets = {"structural": [], "blacklist": [], "value": [], "none": []}
    for c in (parsed.get("clauses") or []):
        if not isinstance(c, dict):
            continue
        text = str(c.get("text") or "").strip()
        if not text:
            continue
        dest = str(c.get("destination") or "").strip().lower()
        entry = {"text": text, "reason": str(c.get("reason") or "").strip()}
        if dest == "structural":
            entry["disclaimer_text"] = str(c.get("disclaimer_text") or "").strip()
            if not entry["disclaimer_text"]:
                entry["reason"] = (entry["reason"] + " (No exact text to check for, so this needs a "
                                   "scored standard rather than a literal check.)").strip()
                buckets["value"].append(entry)
                continue
        elif dest == "blacklist":
            entry["phrase"] = str(c.get("phrase") or "").strip()
            if not entry["phrase"]:
                buckets["value"].append(entry)
                continue
        elif dest not in buckets:
            entry["reason"] = (entry["reason"] + " (Unrecognized classification.)").strip()
            buckets["none"].append(entry)
            continue
        buckets[dest].append(entry)
    return buckets


# Shaped after the real document, including the clauses that must NOT convert.
REAL_POLICY_SHAPED = {
    "clauses": [
        {"text": "Clearly disclose the use of GenAI in AI created or assisted content.",
         "destination": "structural", "reason": "Mandates a disclosure present in the text.",
         "disclaimer_text": "This response was generated with AI assistance and reviewed by a person."},
        {"text": "Anonymize or de-identify all Personal Information before entering data into AI tools.",
         "destination": "value", "reason": "Requires judgment about what counts as personal data."},
        {"text": "Verify that any AI-provided citations are real and relevant.",
         "destination": "value", "reason": "Requires judgment about the citation."},
        {"text": "The steering committee will meet monthly, and more often as needed.",
         "destination": "none", "reason": "Governs a committee, not a response."},
        {"text": "All staff should complete the trainings provided by the organization.",
         "destination": "none", "reason": "An obligation on staff."},
        {"text": "Violations will subject staff to disciplinary action.",
         "destination": "none", "reason": "A consequence for a person."},
    ],
    "definitions": [
        {"term": "Personal Information",
         "enumeration": "name, signature, government-issued identification number, "
                        "social security number, passport number, bank account number"},
    ],
    "notes": [
        "This document references the organization's mission and values but does not state them; "
        "they cannot be derived from it.",
    ],
}


class NormalizationContract(unittest.TestCase):

    def test_01_routes_each_destination(self):
        b = normalize(REAL_POLICY_SHAPED)
        self.assertEqual(len(b["structural"]), 1)
        self.assertEqual(len(b["value"]), 2)
        self.assertEqual(len(b["none"]), 3)
        self.assertEqual(b["blacklist"], [])

    def test_02_process_clauses_never_become_enforceable(self):
        """The whole point. A committee cadence must not end up as a rubric."""
        b = normalize(REAL_POLICY_SHAPED)
        enforceable = b["structural"] + b["blacklist"] + b["value"]
        joined = " ".join(e["text"] for e in enforceable).lower()
        for forbidden in ("steering committee", "trainings", "disciplinary"):
            self.assertNotIn(forbidden, joined,
                             f"a clause about '{forbidden}' reached an enforcing tier")

    def test_03_structural_without_text_is_demoted_not_dropped(self):
        parsed = {"clauses": [{
            "text": "Communicate transparently about capabilities and limitations.",
            "destination": "structural", "reason": "Looks like a disclosure.",
        }]}
        b = normalize(parsed)
        self.assertEqual(b["structural"], [])
        self.assertEqual(len(b["value"]), 1, "the obligation must survive, just in another tier")
        self.assertIn("No exact text to check for", b["value"][0]["reason"])

    def test_04_blacklist_without_phrase_is_demoted(self):
        parsed = {"clauses": [{
            "text": "Never discuss competitor pricing.",
            "destination": "blacklist", "reason": "Sounds like a phrase ban.",
        }]}
        b = normalize(parsed)
        self.assertEqual(b["blacklist"], [])
        self.assertEqual(len(b["value"]), 1)

    def test_05_unknown_destination_falls_back_to_unconvertible(self):
        """Fail toward the tier that enforces nothing. A parse glitch must never
        become a blocking rule."""
        parsed = {"clauses": [{"text": "Something.", "destination": "gate", "reason": "?"}]}
        b = normalize(parsed)
        self.assertEqual(len(b["none"]), 1)
        self.assertIn("Unrecognized", b["none"][0]["reason"])
        self.assertEqual(b["structural"] + b["blacklist"] + b["value"], [])

    def test_06_empty_and_malformed_clauses_are_skipped(self):
        parsed = {"clauses": [
            {"text": "   ", "destination": "value"},
            "not a dict",
            {"destination": "value"},
        ]}
        self.assertEqual(sum(len(v) for v in normalize(parsed).values()), 0)

    def test_07_destination_matching_is_case_insensitive(self):
        parsed = {"clauses": [{"text": "X.", "destination": "VALUE", "reason": "r"}]}
        self.assertEqual(len(normalize(parsed)["value"]), 1)


class DefinitionsFeedRubrics(unittest.TestCase):
    """A policy that enumerates a term is disproportionately valuable: it turns
    'discloses Personal Information' — which the auditor must interpret — into a
    rubric naming the actual categories."""

    def test_enumeration_reaches_the_compile_prompt(self):
        src = Path(pr.__file__).read_text(encoding="utf-8")
        self.assertIn("definitions_block", src)
        self.assertIn("DEFINITIONS FROM THE SOURCE POLICY", src,
                      "compile_rules must pass enumerations through, or the sharpest "
                      "material in a policy document is silently discarded")


class ClassifierPromptGuards(unittest.TestCase):
    """The prompt is the product here. These pin the instructions that stop the
    model inventing rubrics for human obligations."""

    def test_prompt_names_the_always_none_categories(self):
        p = pr._DOC_CLASSIFY_PROMPT.lower()
        for category in ("committee", "training", "questionnaire",
                         "disciplinary", "procurement"):
            self.assertIn(category, p,
                          f"'{category}' clauses are the common false positives; "
                          "the prompt must name them as always-unconvertible")

    def test_prompt_prefers_the_deterministic_tier(self):
        """Per CLAUDE.md: when a control can be expressed either way, put it on
        the side that needs no model."""
        p = pr._DOC_CLASSIFY_PROMPT
        self.assertIn("in order of preference", p)
        self.assertLess(p.index('"structural"'), p.index('"value"'),
                        "the literal tiers must be offered before the model-judged one")

    def test_prompt_asks_for_definitions_and_mission_notes(self):
        p = pr._DOC_CLASSIFY_PROMPT
        self.assertIn("definitions", p)
        self.assertIn("mission", p.lower())

    def test_prompt_refuses_to_invent_a_mission(self):
        """An AI use policy typically REFERENCES the organization's mission and
        defers to a separate code of conduct. Paraphrasing that reference into a
        purpose statement would put words the organization never wrote into the
        frame every agent reasons from."""
        p = pr._DOC_CLASSIFY_PROMPT
        self.assertIn("must NOT be invented", p)

    def test_prompt_asks_for_the_form_fields_the_author_must_fill(self):
        """An import that returns only standards reads as broken: the wizard
        still asks for a name, a purpose and a scope, and the document usually
        supports all three."""
        # Collapse whitespace: the prompt is a wrapped literal, so a phrase can
        # straddle a line break and a naive substring check fails on wording
        # that is in fact present.
        p = pr._DOC_CLASSIFY_PROMPT
        flat = " ".join(p.split())
        self.assertIn('"suggested"', p)
        for field in ('"name"', '"purpose"', '"scope"'):
            self.assertIn(field, p)
        self.assertIn("never invented", flat)

    def test_include_requiring_clauses_route_to_the_literal_tier(self):
        """The live break: a "disclose that AI was used" clause was classified as
        a scored standard, compiled into a -1.0 of "does not include a statement
        about GenAI use", and blocked every response an agent gave.

        A requirement to INCLUDE something can only be broken by omission, so it
        can never be a standard — it belongs to the disclaimer check, which
        appends the missing text instead of refusing the turn."""
        flat = " ".join(pr._DOC_CLASSIFY_PROMPT.split())
        self.assertIn('is ALWAYS "structural" — never "value"', flat)
        self.assertIn("Always supply it", flat)
        self.assertIn("If the only way to fail is by omitting something", flat)

    def test_document_tasks_do_not_use_the_light_model(self):
        """Measured on a real 15-page policy: the light model returned a bare
        "{}" while the Conscience model returned five classified clauses. The
        empty reply PARSES, so it reached the author as "this document contains
        nothing enforceable" — a confident falsehood about their own policy."""
        src = Path(pr.__file__).read_text(encoding="utf-8")
        self.assertIn("_DOCUMENT_TASKS = ('classify_document', 'compile_rules')", src)
        self.assertIn("Config.CONSCIENCE_MODEL if gen_type in _DOCUMENT_TASKS", src)

    def test_a_reply_without_clauses_is_a_failure_not_an_empty_finding(self):
        src = Path(pr.__file__).read_text(encoding="utf-8")
        self.assertIn('"clauses" not in parsed', src)
        self.assertIn("returned an empty result rather than an analysis", src)


class SuggestedFieldsNormalization(unittest.TestCase):
    """`suggested` is written straight into the author's form, so a missing or
    malformed value must land as an empty string rather than "undefined" or a
    crash."""

    def test_endpoint_coerces_every_field_to_a_string(self):
        src = Path(pr.__file__).read_text(encoding="utf-8")
        self.assertIn('for k in ("name", "purpose", "scope")', src)
        self.assertIn("raw_suggested if isinstance(raw_suggested, dict) else {}", src)

    def test_json_branches_sample_at_zero_with_a_real_budget(self):
        """The bug this catches actually happened, on the first real import.

        `compile_rules` inherited the endpoint's drafting defaults — temperature
        0.7 and 4096 tokens — while being asked for strict JSON containing a full
        rubric per standard. It returned unparseable output and the import died
        with a bare 422. Both document branches must set their own sampling:
        latitude produces malformed JSON, and too small a budget truncates it
        mid-object, which looks identical to the caller.
        """
        src = Path(pr.__file__).read_text(encoding="utf-8")
        # Two branches (classify_document, compile_rules) plus the default.
        self.assertEqual(src.count("gen_temperature = 0.0"), 2,
                         "both classify_document and compile_rules must pin temperature 0")
        self.assertEqual(src.count("gen_max_tokens = 8192"), 2,
                         "both must raise the token budget above the 4096 drafting default")

    def test_truncation_is_reported_distinctly_from_malformation(self):
        """A truncated reply and a malformed one need different advice — convert
        fewer at once, versus just retry. A single generic message sent an
        operator hunting through a 15-page document for a clause that was never
        the problem."""
        src = Path(pr.__file__).read_text(encoding="utf-8")
        self.assertIn("cut off before it finished", src)
        self.assertIn("in batches", src)
        self.assertIn('truncated = not cleaned.rstrip().endswith("}")', src)

    def test_normalization_mirror_matches_the_endpoint(self):
        """This file reimplements the endpoint's normalization. If the endpoint's
        branch keys change, the mirror is stale and these tests prove nothing."""
        src = Path(pr.__file__).read_text(encoding="utf-8")
        for key in ('"structural"', '"blacklist"', '"value"', '"none"'):
            self.assertIn(key, src)
        self.assertIn('buckets = {"structural": [], "blacklist": [], "value": [], "none": []}', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
