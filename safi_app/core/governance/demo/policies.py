"""
Demo Business-Unit Policies
===========================
One policy per built-in demo agent. Seeded into the `policies` table at
startup (see database._ensure_demo_agent_policies_exist) with is_demo=TRUE,
then attached to each persona via its `policy_id` key.

Why these exist: SAFi's pitch is that agents are governed by an external,
versioned policy — not by values they author themselves. Before these
policies, every demo agent except contoso_admin was self-governed
(compiled via _standalone_base), which modeled the exact pattern the
platform argues against.

Design notes:
- Each policy LIFTS its persona's scored values (rubrics included) verbatim.
  Under the two-tier compiler an attached policy replaces the persona's
  scored values entirely, so lifting them preserves audit behavior exactly
  while moving the values to where the architecture says they belong.
- scope_statement is likewise lifted into policy_config (policy scope
  overrides agent scope in assemble_agent; same text = no behavior change).
- will_rules stay empty at the policy layer: the persona's own will_rules
  survive the merge untouched, and duplicating them here would double them.
- The worldview is the POLICY voice (organizational constraints), layered
  above the persona's role worldview by assemble_agent.

Once seeded, the DB row is the source of truth — it is versioned and
editable in the Governance tab. Edits here only affect fresh databases.
"""
import copy
from typing import Any, Dict, List

from ...personas.fiduciary import THE_FIDUCIARY_PERSONA
from ...personas.health_navigator import THE_HEALTH_NAVIGATOR_PERSONA
from ...personas.bible_scholar import THE_BIBLE_SCHOLAR_PERSONA
from ...personas.socratic_tutor import THE_SOCRATIC_TUTOR_PERSONA
from ...personas.safi_steward import THE_SAFI_STEWARD_PERSONA
from ...personas.contoso_admin import THE_CONTOSO_ADMIN_PERSONA
from ..contoso.policy import CONTOSO_GLOBAL_POLICY


def _lift_values(values: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Lift persona values to the policy layer. Hard gates get weight 0 — at the
    policy tier a gate is a bright line that blocks on -1, never a component
    of the alignment average (weight ≠ non-negotiability). Scored values keep
    their authored ratios; the compiler renormalizes them to sum to 1.0.
    """
    out = copy.deepcopy(values)
    for v in out:
        if v.get("hard_gate"):
            v["weight"] = 0.0
    return out


def _contoso_policy_values() -> List[Dict[str, Any]]:
    """
    Contoso is the one demo agent whose legacy GOVERNANCE_MAP policy carried
    its OWN values on top of the persona's. Reproduce the legacy compile
    (global values normalized to 0.60 + persona values to 0.40), then merge
    duplicates by name, summing their weights. The legacy path listed the
    three shared values twice (once per tier), double-entering them in every
    audit ledger; per-name totals are identical, so alignment math is
    unchanged — the ledger is just clean now.
    """
    def _norm(vals, target):
        vals = copy.deepcopy(vals)
        total = sum(v.get("weight", 0) for v in vals) or 1.0
        for v in vals:
            v["weight"] = v.get("weight", 0) / total * target
        return vals

    merged: Dict[str, Dict[str, Any]] = {}
    for v in _norm(CONTOSO_GLOBAL_POLICY["global_values"], 0.60) + \
             _norm(THE_CONTOSO_ADMIN_PERSONA["values"], 0.40):
        name = v.get("value") or v.get("name")
        if name in merged:
            merged[name]["weight"] = round(merged[name]["weight"] + v["weight"], 6)
        else:
            v["weight"] = round(v["weight"], 6)
            merged[name] = v
    return list(merged.values())


DEMO_AGENT_POLICIES: Dict[str, Dict[str, Any]] = {

    "demo_contoso_genai_policy": {
        "name": "Contoso GenAI Use Policy",
        "business_unit": "Contoso IT Governance (Demo)",
        "worldview": CONTOSO_GLOBAL_POLICY["global_worldview"],
        # Kept for policy transparency (Governance tab / details modal). The
        # persona's dict-shaped will_rules win the runtime merge, same as the
        # legacy GOVERNANCE_MAP path.
        "will_rules": CONTOSO_GLOBAL_POLICY["global_will_rules"],
        "scope_statement": THE_CONTOSO_ADMIN_PERSONA.get("scope_statement", ""),
        "values": _contoso_policy_values(),
    },

    "demo_financial_advisory_policy": {
        "name": "Financial Advisory Policy",
        "business_unit": "Wealth Management (Demo)",
        "worldview": (
            "You operate under the Financial Advisory Policy.\n\n"
            "Treat these principles as binding organizational constraints:\n"
            "• Education, not advice: Provide financial education and market analysis only. "
            "Never produce personalized investment recommendations or portfolio allocations.\n"
            "• No guarantees: Never promise, project, or imply guaranteed returns. Frame all "
            "market discussion in terms of historical behavior and risk.\n"
            "• Risk transparency: Every discussion of an investment vehicle must acknowledge "
            "its material risks alongside its potential benefits.\n"
            "• Defer to professionals: For decisions with personal financial consequences, "
            "direct the user to a licensed financial advisor.\n"
            "• Source honesty: Distinguish clearly between established market data and "
            "interpretation or opinion."
        ),
        "scope_statement": THE_FIDUCIARY_PERSONA.get("scope_statement", ""),
        "values": _lift_values(THE_FIDUCIARY_PERSONA.get("values", [])),
    },

    "demo_patient_navigation_policy": {
        "name": "Patient Navigation Policy",
        "business_unit": "Health Services (Demo)",
        "worldview": (
            "You operate under the Patient Navigation Policy.\n\n"
            "Treat these principles as binding organizational constraints:\n"
            "• Information, not medicine: Provide health information and system-navigation "
            "guidance only. Never diagnose, prescribe, or adjust treatment.\n"
            "• Safety first: When symptoms described could indicate an emergency, direct the "
            "user to urgent or emergency care before anything else.\n"
            "• Professional referral: Frame guidance so it supports — never replaces — the "
            "user's relationship with their own clinicians.\n"
            "• Respect autonomy: Present options and trade-offs neutrally; the patient makes "
            "the decisions.\n"
            "• No false certainty: Medical evidence has limits; state them plainly."
        ),
        "scope_statement": THE_HEALTH_NAVIGATOR_PERSONA.get("scope_statement", ""),
        "values": _lift_values(THE_HEALTH_NAVIGATOR_PERSONA.get("values", [])),
    },

    "demo_religious_studies_policy": {
        "name": "Religious Studies Policy",
        "business_unit": "Biblical Studies (Demo)",
        "worldview": (
            "You operate under the Religious Studies Policy.\n\n"
            "Treat these principles as binding organizational constraints:\n"
            "• Scholarly grounding: Present biblical and theological material through "
            "historical, linguistic, and literary scholarship.\n"
            "• Textual fidelity: Quote Scripture accurately from the approved translation "
            "and cite book, chapter, and verse.\n"
            "• Denominational neutrality: Where Christian traditions differ, present the "
            "major positions fairly rather than adjudicating between them.\n"
            "• Respect for belief: Treat the faith commitments of users with respect; "
            "scholarship informs, it does not ridicule.\n"
            "• Honest uncertainty: Where the historical record or manuscript evidence is "
            "disputed, say so."
        ),
        "scope_statement": THE_BIBLE_SCHOLAR_PERSONA.get("scope_statement", ""),
        "values": _lift_values(THE_BIBLE_SCHOLAR_PERSONA.get("values", [])),
    },

    "demo_academic_tutoring_policy": {
        "name": "Academic Tutoring Policy",
        "business_unit": "Education (Demo)",
        "worldview": (
            "You operate under the Academic Tutoring Policy.\n\n"
            "Treat these principles as binding organizational constraints:\n"
            "• Guide, don't solve: Lead students to answers through questions and scaffolded "
            "hints. Never hand over a finished solution to work a student must submit.\n"
            "• Academic honesty: Refuse requests to complete graded work, and say why.\n"
            "• Meet the student where they are: Calibrate explanations to the student's "
            "demonstrated level, without condescension.\n"
            "• Errors are material: Treat a student's mistake as the lesson's raw material, "
            "never as grounds for judgment."
        ),
        "scope_statement": THE_SOCRATIC_TUTOR_PERSONA.get("scope_statement", ""),
        "values": _lift_values(THE_SOCRATIC_TUTOR_PERSONA.get("values", [])),
    },

    "demo_product_guidance_policy": {
        "name": "Product Guidance Policy",
        "business_unit": "SAF Institute (Demo)",
        "worldview": (
            "You operate under the Product Guidance Policy.\n\n"
            "Treat these principles as binding organizational constraints:\n"
            "• Documentation is the source of truth: Explain SAF and SAFi from the official "
            "documentation and retrieved material, not from improvisation.\n"
            "• No invented capabilities: Never ascribe features, integrations, pricing, or "
            "roadmap commitments to SAFi that the documentation does not support.\n"
            "• Honest limits: When asked something the documentation does not cover, say so "
            "and point to where an authoritative answer can be obtained.\n"
            "• Clarity over jargon: Prefer plain-language explanation; introduce framework "
            "terminology by defining it."
        ),
        "scope_statement": THE_SAFI_STEWARD_PERSONA.get("scope_statement", ""),
        "values": _lift_values(THE_SAFI_STEWARD_PERSONA.get("values", [])),
    },
}

# persona key -> governing demo policy id (used to stamp the personas and by
# the seeder's sanity logging; the personas also carry this in "policy_id").
DEMO_AGENT_POLICY_MAP: Dict[str, str] = {
    "contoso_admin": "demo_contoso_genai_policy",
    "fiduciary": "demo_financial_advisory_policy",
    "health_navigator": "demo_patient_navigation_policy",
    "bible_scholar": "demo_religious_studies_policy",
    "tutor": "demo_academic_tutoring_policy",
    "safi": "demo_product_guidance_policy",
}
