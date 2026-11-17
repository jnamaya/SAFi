"""Built-in Business-Unit Policies package.

One policy per built-in agent, defined in its own module and aggregated here.
Seeded into the `policies` table at startup by application bootstrap.
"""
from typing import Any, Dict

from .base import _lift_values, lift_values
from .software_engineer import (
    POLICY as SOFTWARE_ENGINEER_POLICY,
    POLICY_ID as SOFTWARE_ENGINEER_POLICY_ID,
    AGENT_KEY as SOFTWARE_ENGINEER_AGENT_KEY,
    AGENTIC_CODING_VALUES,
)
from .sysadmin import (
    POLICY as SYSADMIN_POLICY,
    POLICY_ID as SYSADMIN_POLICY_ID,
    AGENT_KEY as SYSADMIN_AGENT_KEY,
    SYSADMIN_VALUES,
)
from .security_engineer import (
    POLICY as SECURITY_ENGINEER_POLICY,
    POLICY_ID as SECURITY_ENGINEER_POLICY_ID,
    AGENT_KEY as SECURITY_ENGINEER_AGENT_KEY,
    SECURITY_ENGINEER_VALUES,
)

DEMO_AGENT_POLICIES: Dict[str, Dict[str, Any]] = {
    SOFTWARE_ENGINEER_POLICY_ID: SOFTWARE_ENGINEER_POLICY,
    SYSADMIN_POLICY_ID: SYSADMIN_POLICY,
    SECURITY_ENGINEER_POLICY_ID: SECURITY_ENGINEER_POLICY,
}

DEMO_AGENT_POLICY_MAP: Dict[str, str] = {
    SOFTWARE_ENGINEER_AGENT_KEY: SOFTWARE_ENGINEER_POLICY_ID,
    SYSADMIN_AGENT_KEY: SYSADMIN_POLICY_ID,
    SECURITY_ENGINEER_AGENT_KEY: SECURITY_ENGINEER_POLICY_ID,
}


def get_current_demo_policy_ids() -> set[str]:
    return set(DEMO_AGENT_POLICIES.keys())


__all__ = [
    "get_current_demo_policy_ids",
    "DEMO_AGENT_POLICIES",
    "DEMO_AGENT_POLICY_MAP",
    "AGENTIC_CODING_VALUES",
    "SYSADMIN_VALUES",
    "lift_values",
    "_lift_values",
    "SOFTWARE_ENGINEER_POLICY",
    "SYSADMIN_POLICY",
    "SECURITY_ENGINEER_POLICY",
    "SECURITY_ENGINEER_VALUES",
]
