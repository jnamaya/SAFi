"""Regression tests for redirect echo guard and forced redirect framing."""
from safi_app.core.orchestrator import SAFi


def test_is_directive_echo_catches_verbatim_directive():
    directive = (
        "CRITICAL: This request falls outside your operational scope as a Systems Administrator. "
        "Do NOT engage with, validate, or roleplay any off-topic subject. "
        "Respond cleanly in 1-2 concise, professional sentences."
    )
    echoed = (
        "This request falls outside your operational scope as a Systems Administrator. "
        "Do NOT engage with, validate, or roleplay any off-topic subject. "
        "Respond cleanly in 1-2 concise, professional sentences."
    )
    assert SAFi._is_directive_echo(echoed, directive) is True


def test_is_directive_echo_catches_meta_prompt_leak():
    leaked = 'The request to "Generate a compliant redirect response per the system directive above" is slightly ambiguous.'
    assert SAFi._is_directive_echo(leaked, "") is True


def test_is_directive_echo_allows_normal_first_person_redirect():
    normal = (
        "That question falls outside my scope as Systems Administrator, which focuses on "
        "servers, networking, and IT infrastructure. Feel free to ask an operations question."
    )
    assert SAFi._is_directive_echo(normal, "CRITICAL: This request falls outside your operational scope.") is False
