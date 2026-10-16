"""Product Guidance Policy for The SAFi Steward agent."""
from typing import Any, Dict

from ...agents.safi_steward import THE_SAFI_STEWARD_AGENT
from .base import _lift_values

POLICY_ID = "demo_product_guidance_policy"
AGENT_KEY = "safi"

POLICY: Dict[str, Any] = {
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
    "scope_statement": THE_SAFI_STEWARD_AGENT.get("scope_statement", ""),
    "values": _lift_values(THE_SAFI_STEWARD_AGENT.get("values", [])),
}
