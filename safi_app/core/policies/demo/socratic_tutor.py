"""Academic Tutoring Policy for The Socratic Tutor agent."""
from typing import Any, Dict

from ...agents.socratic_tutor import THE_SOCRATIC_TUTOR_AGENT
from .base import _lift_values

POLICY_ID = "demo_academic_tutoring_policy"
AGENT_KEY = "tutor"

POLICY: Dict[str, Any] = {
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
    "scope_statement": THE_SOCRATIC_TUTOR_AGENT.get("scope_statement", ""),
    "values": _lift_values(THE_SOCRATIC_TUTOR_AGENT.get("values", [])),
}
