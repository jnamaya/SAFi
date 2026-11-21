"""Regression tests for org charter injection on built-in agents."""
from unittest.mock import patch

from safi_app.profile_resolver import get_profile


_RUBRIC = {
    "description": "Test rubric",
    "scoring_guide": [
        {"score": 1.0, "descriptor": "Aligned"},
        {"score": -1.0, "descriptor": "Violated"},
    ],
}


def _fake_policy():
    return {
        "policy_id": "prod_systems_admin_policy",
        "name": "Pro Systems Admin",
        "version": 1,
        "org_id": None,
        "is_demo": True,
        "worldview": "",
        "values_weights": [
            {"value": "Change Safety & Reversibility", "weight": 1.0, "hard_gate": False, "rubric": _RUBRIC}
        ],
        "will_rules": {},
        "policy_config": {},
    }


def test_builtin_agent_receives_caller_org_charter_when_defined():
    charter = {
        "mission": "Protect patient care through reliable infrastructure.",
        "core_values": [
            {"name": "Patient Privacy First", "definition": "Protect PHI at all times.", "weight": 1.0, "rubric": _RUBRIC}
        ],
    }
    with patch("safi_app.profile_resolver.db.get_policy", return_value=_fake_policy()), \
         patch("safi_app.profile_resolver.db.get_organization", return_value={"name": "Acme Health", "settings": {}}), \
         patch("safi_app.profile_resolver.db.get_charter", return_value=charter), \
         patch("safi_app.profile_resolver.db.get_ai_standards", return_value=None):
        prof = get_profile("sysadmin", org_id="org-123")

    assert prof["has_charter"] is True
    assert prof["org_id"] == "org-123"
    assert prof["org_name"] == "Acme Health"
    assert "--- Organization Context ---" in prof["worldview"]
    assert "Protect patient care through reliable infrastructure." in prof["worldview"]
    assert "Patient Privacy First" in prof["worldview"]
    assert any(v.get("value") == "Patient Privacy First" for v in prof["values"])


def test_builtin_agent_gets_no_charter_context_when_org_has_none():
    with patch("safi_app.profile_resolver.db.get_policy", return_value=_fake_policy()), \
         patch("safi_app.profile_resolver.db.get_organization", return_value={"name": "Acme Health", "settings": {}}), \
         patch("safi_app.profile_resolver.db.get_charter", return_value=None), \
         patch("safi_app.profile_resolver.db.get_ai_standards", return_value=None):
        prof = get_profile("sysadmin", org_id="org-123")

    assert prof["has_charter"] is False
    assert "--- Organization Context ---" not in prof["worldview"]


def test_builtin_agent_without_org_id_does_not_inject_charter():
    with patch("safi_app.profile_resolver.db.get_policy", return_value=_fake_policy()):
        prof = get_profile("sysadmin")

    assert prof["has_charter"] is False
    assert prof["org_id"] is None
    assert "--- Organization Context ---" not in prof["worldview"]
