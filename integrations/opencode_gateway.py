"""
Standalone OpenAI-compatible gateway for opencode and similar clients.

A thin adapter, not part of the SAFi Flask app: it speaks the OpenAI
chat-completions protocol on the inbound side and forwards every turn to the
SAFi backend's /api/bot/process_prompt endpoint, the same governed pipeline the
Teams and Telegram bots use. It deliberately holds no governance logic — agent
selection, policy resolution, orchestration and audit all happen in the backend.

Because it is a standalone process (like integrations/teams_bot.py and
integrations/telegram_bot.py), the SAFi application itself no longer carries a
/v1 route. A reverse proxy points /v1/ at this service's port.

Protocol mapping:
  * The client's `model` field (e.g. "safinstitute_org_runsafi_business_development_agent")
    is passed through as the backend's `agent` persona. A client that sends no
    model falls back to the SAFI_OPENAI_PERSONA env var, or "safi".
  * Auth is the policy API key shared by client and adapter: opencode.json and
    this process read the same SAFI_POLICY_API_KEY. The adapter checks it and
    forwards it to the backend as `X-API-KEY`; the backend resolves it against
    the api_keys table to pick the governing policy.
  * Conversation continuity rides on `user_id` and `conversation_id`, supplied
    by the client via the `user` request field, like the other bots.
"""

import json
import os
import sys
import time
import hashlib
import uuid

import requests
from flask import Flask, Response, jsonify, request

# --- Configuration (mirrors the bot integrations) ---
SAFI_API_URL = os.environ.get(
    "SAFI_OPENAI_API_URL",
    "http://localhost:5001/api/bot/process_prompt",
)
# The policy API key this integration is bound to: minted in the SAFi policy
# UI against the policy you want governing the turns. The opencode client sends
# the SAME key (opencode.json apiKey), so the adapter can authenticate the
# caller AND forward the key to the backend in one value. Single-policy per
# adapter instance, exactly like the Teams/Telegram bots.
SAFI_API_KEY = os.environ.get("SAFI_POLICY_API_KEY", "")
# Fallback persona when the client sends no `model`.
PERSONA = os.environ.get("SAFI_OPENAI_PERSONA", "safi")
PORT = int(os.environ.get("SAFI_OPENAI_PORT", "5002"))
# Model ids advertised by /models, so opencode-style clients can list the
# agents this deployment serves. Comma-separated; "safi" is the built-in.
MODEL_IDS = [
    m.strip() for m in os.environ.get("SAFI_OPENAI_MODELS", "safi").split(",")
    if m.strip()
]
_OPENAI_GOVERNED_MODEL_LIST = {
    "id": "safi",
    "object": "model",
    "owned_by": "self-alignment-framework",
}

app = Flask(__name__)


def _model_list():
    out = []
    for mid in MODEL_IDS:
        entry = dict(_OPENAI_GOVERNED_MODEL_LIST)
        entry["id"] = mid
        out.append(entry)
    return out


def _client_api_key() -> str:
    """Read the policy API key from the inbound request (Bearer or X-API-KEY)."""
    key = request.headers.get("X-API-KEY") or request.headers.get("Authorization", "")
    if key.startswith("Bearer "):
        key = key[len("Bearer "):]
    return key


def _error(payload, status):
    return jsonify({"error": payload}), status


def _conversation_id(user: str) -> str:
    """A stable, high-entropy conversation id per client user (36-char ceiling)."""
    if user:
        digest = hashlib.sha256(user.encode()).hexdigest()[:31]
        return f"oc_{digest}"
    return f"oc_{uuid.uuid4().hex[:28]}"


@app.route("/models", methods=["GET"])
def models_list():
    return jsonify({"object": "list", "data": _model_list()})


@app.route("/chat/completions", methods=["POST"])
def chat_completions_endpoint():
    api_key = _client_api_key()
    if not api_key or api_key != SAFI_API_KEY:
        return _error({
            "message": "Invalid policy API key.",
            "type": "authentication_error",
            "code": "invalid_api_key",
        }, 401)

    if not SAFI_API_KEY:
        return _error({
            "message": "Server not configured: SAFI_POLICY_API_KEY is unset.",
            "type": "server_error",
            "code": "server_not_configured",
        }, 500)

    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        return _error({
            "message": "Request body must be valid JSON.",
            "type": "invalid_request_error",
            "code": "invalid_json",
        }, 400)

    messages = data.get("messages") or []
    if not isinstance(messages, list) or not messages:
        return _error({
            "message": "`messages` is required and must be a non-empty array.",
            "type": "invalid_request_error",
            "code": "missing_messages",
        }, 400)

    stream = bool(data.get("stream", False))
    model = data.get("model") or PERSONA

    # Latest user text is what the backend /api/bot pipeline reasons from; it
    # holds conversation history itself keyed by conversation_id.
    last_user = None
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role != "user":
            continue
        if isinstance(content, list):
            bits = []
            for part in content:
                if isinstance(part, dict) and (part.get("text") or part.get("content")):
                    bits.append(str(part["text"] or part.get("content")))
                elif isinstance(part, str):
                    bits.append(part)
            text = "\n".join(bits)
        else:
            text = str(content or "")
        text = text.strip()
        if text:
            last_user = text

    if not last_user:
        return _error({
            "message": "No user message found.",
            "type": "invalid_request_error",
            "code": "empty_user_message",
        }, 400)

    user = data.get("user")
    conversation_id = _conversation_id(user)

    payload = {
        "message": last_user,
        "user_id": user or f"opencode_{uuid.uuid4().hex[:12]}",
        "conversation_id": conversation_id,
        "agent": model,   # the SAFi persona = the agent key
    }
    headers = {"X-API-KEY": SAFI_API_KEY, "Content-Type": "application/json"}

    try:
        resp = requests.post(SAFI_API_URL, json=payload, headers=headers, timeout=240)
    except requests.exceptions.RequestException as exc:
        current_app_like_err = f"Backend unreachable: {exc}"
        print(f"OpenAI gateway error: {current_app_like_err}", file=sys.stderr)
        return _error({
            "message": "The governed backend is unreachable.",
            "type": "server_error",
            "code": "backend_unreachable",
        }, 502)

    if resp.status_code != 200:
        return _error({
            "message": "The governed backend rejected the turn.",
            "type": "upstream_error",
            "code": "upstream_turn_failed",
            "detail": resp.text[:2000],
        }, 502)

    result = resp.json()
    text = (result or {}).get("finalOutput") or ""
    message_id = (result or {}).get("messageId") or uuid.uuid4().hex
    chat_id = f"chatcmpl-{message_id}"
    created = int(time.time())

    _safi_headers = {
        "X-SAFi-Message-Id": message_id,
        "X-SAFi-Policy-Id": str((result or {}).get("policy_id") or ""),
        "X-SAFi-Will-Decision": str((result or {}).get("willDecision") or "approve"),
        "X-SAFi-Spirit-Score": str((result or {}).get("spirit_score") or ""),
    }
    if data.get("tools"):
        _safi_headers["X-SAFi-Note"] = (
            "tool calling is not enabled on this gateway; "
            "responded with a governed text turn"
        )

    if not stream:
        out = jsonify({
            "id": chat_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }],
        })
        out.headers["X-AI-Generated"] = "true"
        for name, value in _safi_headers.items():
            out.headers[name] = value
        return out

    def _chunk(payload_obj):
        return f"data: {json.dumps(payload_obj)}\n\n"

    def _generator():
        yield _chunk({
            "id": chat_id, "object": "chat.completion.chunk", "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""},
                         "finish_reason": None}],
        })
        for i in range(0, len(text), 16):
            yield _chunk({
                "id": chat_id, "object": "chat.completion.chunk", "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"content": text[i:i + 16]},
                             "finish_reason": None}],
            })
        yield _chunk({
            "id": chat_id, "object": "chat.completion.chunk", "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        })
        yield "data: [DONE]\n\n"

    headers = {"X-AI-Generated": "true", "Cache-Control": "no-cache",
               "X-Accel-Buffering": "no"}
    headers.update(_safi_headers)
    return Response(_generator(), mimetype="text/event-stream", headers=headers)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT, threaded=True)