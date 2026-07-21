# safi_app/core/provenance.py
"""Machine-readable AI-output marking (EU AI Act Art. 50(2)).

Every surface that delivers AI-generated content — chat responses, the
evaluation gateway, TTS audio, and record exports — carries a marker that
identifies the content as artificially generated, in a format a downstream
machine can detect without parsing prose:

- JSON responses embed an ``aiProvenance`` object (see :func:`ai_marker`).
- HTTP responses additionally carry an ``X-AI-Generated: true`` header, so
  intermediaries and non-JSON consumers (e.g. the TTS audio stream) can
  detect the marking without reading the body.
- Exported records mark each AI message with ``ai_generated: true``.

Art. 50(1)'s human-facing disclosure shipped separately (Phase A); this
module is the Art. 50(2) machine-readable layer. The marker states
provenance only — it makes no quality or compliance claim (vocabulary
rules: no capability language).
"""
from datetime import datetime, timezone

GENERATOR = "SAFi"
MARKING_STANDARD = "EU-AI-Act-Art-50(2)"
AI_HEADER = "X-AI-Generated"


def ai_marker(model=None, evaluator_only=False):
    """The machine-readable provenance object embedded in JSON responses.

    evaluator_only: the /evaluate gateway marks content that an EXTERNAL
    agent generated and SAFi only evaluated — the marker must not claim
    SAFi generated it."""
    marker = {
        "ai_generated": True,
        "marking_standard": MARKING_STANDARD,
        "marked_at": datetime.now(timezone.utc).isoformat(),
    }
    if evaluator_only:
        marker["evaluator"] = GENERATOR
        marker["generator"] = "external-agent"
    else:
        marker["generator"] = GENERATOR
    if model:
        marker["model"] = model
    return marker


def mark_json_response(response):
    """Stamps the machine-readable header on a Flask response."""
    response.headers[AI_HEADER] = "true"
    return response
