"""
Standalone OpenAI-compatible gateway for opencode and similar clients.

A thin adapter, not part of the SAFi Flask app: it speaks the OpenAI
chat-completions protocol on the inbound side and forwards every turn to the
SAFi backend's /api/harness/process_prompt endpoint, the harness integration
path that supports streaming and native tool calling. It deliberately holds no
governance logic — agent selection, policy resolution, orchestration and audit
all happen in the backend.

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
  * Tool calling: the client's `tools` array is passed through to the backend.
    SAFi gates each proposal; OpenCode executes approved calls natively and
    sends results back on the next request.
  * Workspace metadata: only OpenCode's runtime working-directory and workspace
    root lines are extracted from its system messages. The rest of its system
    prompt is not forwarded into SAFi's governed prompt.
"""

import json
import os
import re
import sys
import threading
import time
import hashlib
import uuid

import requests
from flask import Flask, Response, jsonify, request

# --- Configuration (mirrors the bot integrations) ---
SAFI_API_URL = os.environ.get(
    "SAFI_OPENAI_API_URL",
    "http://localhost:5001/api/harness/process_prompt",
)
SAFI_PROGRESS_URL = os.environ.get(
    "SAFI_OPENAI_PROGRESS_URL",
    f"{SAFI_API_URL.rsplit('/', 1)[0]}/progress",
)
# The policy API key this integration is bound to: minted in the SAFi policy
# UI against the policy you want governing the turns. The opencode client sends
# the SAME key (opencode.json apiKey), so the adapter can authenticate the
# caller AND forward the key to the backend in one value. Single-policy per
# adapter instance, exactly like the Teams/Telegram bots.
SAFI_API_KEY = os.environ.get("SAFI_POLICY_API_KEY", "")
# Fallback persona when the client sends no `model`.
PERSONA = os.environ.get("SAFI_OPENAI_PERSONA", "safi")
# Stable actor identity for turns this adapter sends. opencode does not send a
# `user` field, so deriving one per request would mint a new user row every turn
# and scatter the audit trail across dozens of throwaway actors. Derived from the
# policy API key so it is stable across restarts and still separates deployments
# that use different policies. Override to attribute turns to a real operator.
HARNESS_USER = os.environ.get("SAFI_OPENAI_USER") or (
    f"opencode_harness_{hashlib.sha256(SAFI_API_KEY.encode()).hexdigest()[:12]}"
    if SAFI_API_KEY else ""
)
PORT = int(os.environ.get("SAFI_OPENAI_PORT", "5002"))
HOST = os.environ.get("SAFI_OPENAI_HOST", "127.0.0.1")
# Model ids advertised by /models, so opencode-style clients can list the model
# aliases this deployment serves. Use SAFI_OPENAI_AGENT_MAP to route aliases to
# actual registered SAFi profiles.
MODEL_IDS = [
    m.strip() for m in os.environ.get("SAFI_OPENAI_MODELS", "safi").split(",")
    if m.strip()
]
try:
    MODEL_AGENT_MAP = json.loads(os.environ.get("SAFI_OPENAI_AGENT_MAP", "{}"))
except (TypeError, ValueError):
    MODEL_AGENT_MAP = {}
if not isinstance(MODEL_AGENT_MAP, dict):
    MODEL_AGENT_MAP = {}
try:
    MODEL_CONNECTOR_MAP = json.loads(os.environ.get("SAFI_OPENAI_CONNECTOR_MAP", "{}"))
except (TypeError, ValueError):
    MODEL_CONNECTOR_MAP = {}
if not isinstance(MODEL_CONNECTOR_MAP, dict):
    MODEL_CONNECTOR_MAP = {}
_OPENAI_GOVERNED_MODEL_LIST = {
    "id": "safi",
    "object": "model",
    "owned_by": "self-alignment-framework",
}

app = Flask(__name__)

_PROGRESS_TEXT = {
    "checking_request": "Checking request safeguards…",
    "analyzing": "Analyzing the request…",
    "checking_tool": "Checking the proposed tool call…",
    "structure": "Checking response structure…",
    "auditing": "Auditing the response against policy…",
    "alignment": "Checking governance alignment…",
    "finalizing": "Finalizing the governed response…",
}


def _completion_chunk(chat_id, created, model, delta, finish_reason=None):
    return {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def _sse_data(payload):
    return f"data: {json.dumps(payload)}\n\n"


def _openai_usage(usage):
    """Normalize real SAFi provider counts to Chat Completions usage fields."""
    if not isinstance(usage, dict):
        return None
    try:
        prompt = max(0, int(usage["prompt_tokens"]))
        completion = max(0, int(usage["completion_tokens"]))
    except (KeyError, TypeError, ValueError):
        return None
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def _coding_harness_tool_schemas():
    """SAFi-reviewed schema declarations for the OpenCode tool vocabulary."""
    return [
        {"type": "function", "function": {
            "name": "read", "description": "Read a file from the current workspace.",
            "parameters": {"type": "object", "properties": {
                "filePath": {"type": "string"}, "path": {"type": "string"},
                "offset": {"type": "integer"}, "limit": {"type": "integer"},
            }, "anyOf": [{"required": ["filePath"]}, {"required": ["path"]}]},
        }},
        {"type": "function", "function": {
            "name": "grep", "description": "Search workspace file contents.",
            "parameters": {"type": "object", "properties": {
                "pattern": {"type": "string"}, "path": {"type": "string"},
                "include": {"type": "string"}, "limit": {"type": "integer"},
            }, "required": ["pattern"]},
        }},
        {"type": "function", "function": {
            "name": "glob", "description": "Find workspace files by glob pattern.",
            "parameters": {"type": "object", "properties": {
                "pattern": {"type": "string"}, "path": {"type": "string"},
            }, "required": ["pattern"]},
        }},
        {"type": "function", "function": {
            "name": "list", "description": "List entries in a workspace directory.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string"},
            }},
        }},
    ]


def _stream_backend_turn(payload, headers, model, message_id):
    """Poll SAFi's safe phase codes while its governed turn runs in parallel."""
    chat_id = f"chatcmpl-{message_id}"
    created = int(time.time())

    def generate():
        result = {}
        completed = threading.Event()

        def run_backend():
            try:
                result["response"] = requests.post(
                    SAFI_API_URL, json=payload, headers=headers, timeout=240
                )
            except requests.exceptions.RequestException as exc:
                result["error"] = exc
            finally:
                completed.set()

        worker = threading.Thread(target=run_backend, daemon=True)
        worker.start()
        yield _sse_data(_completion_chunk(
            chat_id, created, model, {"role": "assistant", "content": ""}
        ))

        emitted = set()

        def progress_chunks():
            try:
                progress_response = requests.get(
                    f"{SAFI_PROGRESS_URL}/{message_id}",
                    headers=headers,
                    params={"user_id": payload.get("user_id", "")},
                    timeout=(1, 2),
                )
                if progress_response.status_code != 200:
                    return []
                codes = progress_response.json().get("progress", [])
            except (requests.exceptions.RequestException, ValueError, TypeError, AttributeError):
                return []
            chunks = []
            if not isinstance(codes, list):
                return chunks
            for code in codes:
                text = _PROGRESS_TEXT.get(code)
                if text and code not in emitted:
                    emitted.add(code)
                    chunks.append(_sse_data(_completion_chunk(
                        chat_id, created, model,
                        {"reasoning_content": f"SAFi: {text}\n"},
                    )))
            return chunks

        while not completed.is_set():
            yield from progress_chunks()
            completed.wait(0.35)
        # The backend commits its final progress/audit state before replying.
        yield from progress_chunks()

        response = result.get("response")
        if response is None or response.status_code != 200:
            status = response.status_code if response is not None else "unavailable"
            detail = ""
            if response is not None:
                try:
                    body = response.json()
                    if isinstance(body, dict):
                        detail = str(body.get("error") or body.get("willReason") or "")[:800]
                except (ValueError, TypeError):
                    detail = ""
            error_text = f"SAFi could not complete this governed request (backend {status})."
            if detail:
                error_text += f" {detail}"
            yield _sse_data(_completion_chunk(
                chat_id, created, model, {"content": error_text}
            ))
            yield _sse_data(_completion_chunk(
                chat_id, created, model, {}, "stop"
            ))
            yield "data: [DONE]\n\n"
            return

        try:
            governed = response.json()
        except (ValueError, TypeError):
            governed = {}

        if governed.get("type") == "tool_call":
            tool_call_id = f"toolu_{uuid.uuid4().hex[:24]}"
            yield _sse_data(_completion_chunk(
                chat_id, created, model,
                {"tool_calls": [{
                    "index": 0,
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": governed.get("tool_name", ""),
                        "arguments": json.dumps(governed.get("parameters", {})),
                    },
                }]},
            ))
            yield _sse_data(_completion_chunk(chat_id, created, model, {}, "tool_calls"))
            usage = _openai_usage(governed.get("token_usage"))
            if usage:
                yield _sse_data({
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [],
                    "usage": usage,
                })
            yield "data: [DONE]\n\n"
            return

        text = governed.get("finalOutput") or ""
        for index in range(0, len(text), 16):
            yield _sse_data(_completion_chunk(
                chat_id, created, model, {"content": text[index:index + 16]}
            ))
        yield _sse_data(_completion_chunk(chat_id, created, model, {}, "stop"))
        usage = _openai_usage(governed.get("token_usage"))
        if usage:
            yield _sse_data({
                "id": chat_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [],
                "usage": usage,
            })
        yield "data: [DONE]\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-AI-Generated": "true",
            "X-SAFi-Message-Id": message_id,
        },
    )


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


_WORKSPACE_LINE = re.compile(
    r"^\s*(Working directory|Workspace root folder):\s*(.*?)\s*$",
    re.MULTILINE,
)


def _content_text(content) -> str:
    """Flatten OpenAI text content without forwarding non-text payloads."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text") or part.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


def _tool_arguments(value):
    """Normalize the JSON-string or object shape used by OpenAI tool calls."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _extract_workspace_context(messages):
    """Extract only OpenCode's explicit cwd/worktree metadata from system text.

    OpenCode 1.18.34 puts these two lines inside its system `<env>` block.
    Forwarding the full client system prompt could override SAFi's governance
    prompt; dropping it entirely leaves the model to invent filesystem paths.
    """
    found = {}
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "system":
            continue
        for label, value in _WORKSPACE_LINE.findall(_content_text(message.get("content"))):
            value = value.strip().strip("`\"'")
            if value.startswith("/") and len(value) <= 2048 and not any(
                ch in value for ch in ("\x00", "\r", "\n")
            ):
                found[label] = os.path.normpath(value)
    return {
        "working_directory": found.get("Working directory"),
        "workspace_root": found.get("Workspace root folder"),
    }


def _extract_user_and_tool_results(messages):
    """Return latest user text and only tool results after that user turn.

    OpenCode sends a full transcript on each request. Collecting every `role=tool`
    row duplicates old results in every later SAFi prompt. The tool result's
    `tool_call_id` also needs joining to the preceding assistant tool call to
    recover the actual name and arguments.
    """
    if not isinstance(messages, list):
        return None, []

    last_user_index = None
    last_user = None
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        text = _content_text(message.get("content")).strip()
        if text:
            last_user_index = index
            last_user = text

    if last_user_index is None:
        return None, []

    calls_by_id = {}
    results = []
    for message in messages[last_user_index + 1:]:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "assistant":
            for call in message.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                function = call.get("function") or {}
                call_id = call.get("id")
                name = function.get("name")
                if call_id and isinstance(name, str):
                    calls_by_id[call_id] = {
                        "tool_name": name,
                        "arguments": _tool_arguments(function.get("arguments")),
                    }
        elif role == "tool":
            call_id = message.get("tool_call_id")
            metadata = calls_by_id.get(call_id, {})
            content = message.get("content")
            results.append({
                "tool_name": message.get("name") or metadata.get("tool_name") or "unknown",
                "arguments": _tool_arguments(message.get("arguments")) or metadata.get("arguments", {}),
                "result": content if isinstance(content, str) else json.dumps(content),
            })

    return last_user, results


def _extract_recent_turns(messages, max_chars=12000, max_messages=24):
    """Format bounded prior transcript context, excluding the current user turn.

    The harness endpoint is stateless at the HTTP level. OpenCode sends the
    transcript, so this adapter must forward prior conversational turns rather
    than only `last_user`; otherwise the backend's `recent_turns` injection is
    empty even though the client has the history. Current-turn tool results are
    handled separately by `_extract_user_and_tool_results` to avoid duplicating
    them in both prompt channels.
    """
    if not isinstance(messages, list):
        return ""

    last_user_index = None
    for index, message in enumerate(messages):
        if (isinstance(message, dict) and message.get("role") == "user"
                and _content_text(message.get("content")).strip()):
            last_user_index = index
    if last_user_index is None:
        return ""

    prior = messages[:last_user_index]
    calls_by_id = {}
    for message in prior:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            function = call.get("function") or {}
            if call.get("id") and isinstance(function.get("name"), str):
                calls_by_id[call["id"]] = {
                    "tool_name": function["name"],
                    "arguments": _tool_arguments(function.get("arguments")),
                }

    lines = []
    for message in prior[-max_messages:]:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "user":
            text = _content_text(message.get("content")).strip()
            if text:
                lines.append(f"User: {text}")
        elif role == "assistant":
            text = _content_text(message.get("content")).strip()
            if text:
                lines.append(f"Assistant: {text}")
            for call in message.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                function = call.get("function") or {}
                name = function.get("name") or "unknown"
                args = _tool_arguments(function.get("arguments"))
                lines.append(
                    f"Assistant proposed tool: {name}"
                    f"({json.dumps(args, sort_keys=True, default=str)})"
                )
        elif role == "tool":
            call_id = message.get("tool_call_id")
            metadata = calls_by_id.get(call_id, {})
            name = message.get("name") or metadata.get("tool_name") or "unknown"
            args = _tool_arguments(message.get("arguments")) or metadata.get("arguments", {})
            content = message.get("content")
            result = content if isinstance(content, str) else json.dumps(content)
            lines.append(
                f"Tool result: {name}({json.dumps(args, sort_keys=True, default=str)})\n{result}"
            )

    history = "\n\n".join(lines)
    if len(history) > max_chars:
        history = "[Earlier conversation context truncated]\n" + history[-max_chars:]
    return history


@app.route("/models", methods=["GET"])
@app.route("/v1/models", methods=["GET"])
def models_list():
    return jsonify({"object": "list", "data": _model_list()})


@app.route("/chat/completions", methods=["POST"])
@app.route("/v1/chat/completions", methods=["POST"])
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
    agent = MODEL_AGENT_MAP.get(model, model)

    last_user, collected_tool_results = _extract_user_and_tool_results(messages)
    workspace_context = _extract_workspace_context(messages)
    recent_turns = _extract_recent_turns(messages)

    if not last_user:
        return _error({
            "message": "No user message found.",
            "type": "invalid_request_error",
            "code": "empty_user_message",
        }, 400)

    user = data.get("user") or HARNESS_USER
    conversation_id = _conversation_id(user)

    payload = {
        "message": last_user,
        "user_id": user,
        "conversation_id": conversation_id,
        "agent": agent,
        "workspace_context": workspace_context,
        "recent_turns": recent_turns,
    }

    if data.get("tools"):
        payload["tools"] = list(data["tools"])
    if data.get("tool_results"):
        payload["tool_results"] = data["tool_results"]
    elif collected_tool_results:
        payload["tool_results"] = collected_tool_results

    headers = {"X-API-KEY": SAFI_API_KEY, "Content-Type": "application/json"}

    if stream:
        message_id = str(uuid.uuid4())
        payload["message_id"] = message_id
        return _stream_backend_turn(payload, headers, model, message_id)

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

    # Handle tool_call response — return to harness for native execution
    if result.get("type") == "tool_call":
        tool_call_id = f"toolu_{uuid.uuid4().hex[:24]}"
        function_name = result.get("tool_name", "")
        function_arguments = json.dumps(result.get("parameters", {}))
        usage = _openai_usage(result.get("token_usage"))
        return jsonify({
            "id": f"chatcmpl-{tool_call_id}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                            "id": tool_call_id,
                            "type": "function",
                            "function": {
                                "name": function_name,
                                "arguments": function_arguments,
                        }
                    }]
                },
                "finish_reason": "tool_calls",
            }],
            **({"usage": usage} if usage else {}),
        })

    text = (result or {}).get("finalOutput") or ""
    usage = _openai_usage((result or {}).get("token_usage"))
    message_id = (result or {}).get("messageId") or uuid.uuid4().hex
    chat_id = f"chatcmpl-{message_id}"
    created = int(time.time())

    _safi_headers = {
        "X-SAFi-Message-Id": message_id,
        "X-SAFi-Policy-Id": str((result or {}).get("policy_id") or ""),
        "X-SAFi-Will-Decision": str((result or {}).get("willDecision") or "approve"),
        "X-SAFi-Spirit-Score": str((result or {}).get("spirit_score") or ""),
    }

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
        **({"usage": usage} if usage else {}),
    })
    out.headers["X-AI-Generated"] = "true"
    for name, value in _safi_headers.items():
        out.headers[name] = value
    return out


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, threaded=True)
