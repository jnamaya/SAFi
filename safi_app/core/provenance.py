from datetime import datetime, timezone

GENERATOR = "SAFi"
MARKING_STANDARD = "EU-AI-Act-Art-50(2)"
AI_HEADER = "X-AI-Generated"


def ai_marker(model=None, evaluator_only=False):
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
    response.headers[AI_HEADER] = "true"
    return response
