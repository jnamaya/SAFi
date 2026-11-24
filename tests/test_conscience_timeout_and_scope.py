import asyncio
from unittest.mock import patch

from safi_app.core.policies.runtime_defaults import scope_compliance_value
from safi_app.core.services import llm_provider as lp


def test_scope_compliance_rubric_marks_clean_refusal_compliant():
    val = scope_compliance_value("IT systems administration")
    desc = val["rubric"]["description"]
    neg = next(g["descriptor"] for g in val["rubric"]["scoring_guide"] if g["score"] == -1.0)
    assert "MUST be scored +1.0, NEVER -1.0" in desc
    assert "cleanly refused an out-of-scope request" in neg


def test_run_conscience_times_out_fast_on_json_mode_and_recovers():
    provider = lp.LLMProvider.__new__(lp.LLMProvider)
    provider.log = lp.logging.getLogger("test_conscience")

    calls = []

    async def fake_chat_completion(**kwargs):
        calls.append(kwargs.get("json_mode", False))
        if kwargs.get("json_mode"):
            await asyncio.sleep(0.2)
            return "{}"
        return '{"evaluations": [{"value": "Scope Compliance", "score": 1.0, "confidence": 0.9, "reason": "Clean refusal"}]}'

    provider._chat_completion = fake_chat_completion

    with patch.object(lp, "CONSCIENCE_TIMEOUT_SECONDS", 0.05):
        ledger = asyncio.run(provider.run_conscience("sys", "user"))

    assert calls == [True, False]
    assert len(ledger) == 1
    assert ledger[0]["value"] == "Scope Compliance"
    assert ledger[0]["score"] == 1.0
