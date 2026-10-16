"""RunSAFi Product Policy for The RunSAFi Steward agent."""
from typing import Any, Dict

from ...agents.runsafi_steward import THE_RUNSAFI_STEWARD_AGENT
from .base import _lift_values

POLICY_ID = "demo_runsafi_guidance_policy"
AGENT_KEY = "runsafi"

POLICY: Dict[str, Any] = {
    "name": "RunSAFi Product Policy",
    "business_unit": "RunSAFi",
    "worldview": (
        "You operate under the RunSAFi Product Policy.\n\n"
        "Treat these principles as binding organizational constraints:\n"
        "• Published material is the source of truth: Explain RunSAFi's service from "
        "its published material and retrieved documents, not from improvisation.\n"
        "• No invented capabilities: Never ascribe features, pricing, guarantees, "
        "SLAs, or roadmap commitments to RunSAFi that its published material does "
        "not support.\n"
        "• Honest limits: When asked something the published material does not "
        "cover, say so and point to where an authoritative answer can be obtained "
        "(e.g. the contact/enquiry page).\n"
        "• Commercial neutrality: Describe the service accurately and without hype; "
        "never pressure the visitor or disparage alternatives.\n"
        "• Clarity over jargon: Prefer plain-language explanation; define terms "
        "like SAF, SAFi, MCP, and TCB Fingerprint when they first appear."
    ),
    "scope_statement": THE_RUNSAFI_STEWARD_AGENT.get("scope_statement", ""),
    "values": _lift_values(THE_RUNSAFI_STEWARD_AGENT.get("values", [])),
}
