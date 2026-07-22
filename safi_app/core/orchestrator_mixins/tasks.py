"""
Mixin for background task management (summarization, profile extraction).
"""
from __future__ import annotations
import json as _json
from ...persistence import database as db
from ...config import Config
from ..services.model_routing import detect_provider
from ..services.provider_governance import assert_provider_allowed, ProviderNotAllowedError


# --- Work-context memory: deterministic merge ----------------------------------
# The extractor LLM emits only a DELTA (upserts/removals) for the latest exchange.
# We merge it into the stored memory in Python so existing items can NEVER be
# silently dropped just because the model didn't re-type them. This is the
# durability guarantee — it does not depend on the model behaving.

# Ordered list categories and the field that identifies one entry within a list.
_CTX_LIST_FIELDS = ["projects", "tasks", "decisions", "people", "milestones", "vendors", "notes"]
_CTX_ID_FIELD = {
    "projects": "name",
    "tasks": "task",
    "decisions": "question",
    "people": "name",
    "vendors": "name",
}
# Soft cap per list (high enough that normal use never hits it; only guards runaway growth).
_CTX_CAP = 40


def _ctx_norm(s) -> str:
    return (s or "").strip().lower() if isinstance(s, str) else ""


def _ctx_identity(cat: str, item) -> str:
    """Stable identity for an entry, used for upsert-in-place, dedup, and removal."""
    if not isinstance(item, dict):
        return ""
    if cat == "milestones":
        return _ctx_norm(item.get("event")) + "|" + _ctx_norm(item.get("date"))
    return _ctx_norm(item.get(_CTX_ID_FIELD.get(cat, "")))


def merge_agent_context(current: dict, delta: dict) -> dict:
    """
    Merge a model-produced delta into the stored work-context memory.

    Additive by default: any existing entry the delta does not explicitly upsert
    or remove is carried forward unchanged. Accepts either the delta shape
    ({"upserts": {...}, "removals": {...}}) or a legacy full-object shape (whose
    present categories are treated as upserts) — both are safe, neither drops data.
    """
    current = current if isinstance(current, dict) else {}
    out = {k: list(current.get(k) or []) for k in _CTX_LIST_FIELDS}

    if isinstance(delta, dict) and ("upserts" in delta or "removals" in delta):
        upserts = delta.get("upserts") or {}
        removals = delta.get("removals") or {}
    elif isinstance(delta, dict):
        # Legacy/full-object output — treat present categories as upserts (still additive).
        upserts = {k: delta.get(k) for k in _CTX_LIST_FIELDS if k in delta}
        removals = {}
    else:
        upserts, removals = {}, {}

    # --- Apply upserts ---
    for cat in _CTX_LIST_FIELDS:
        items = upserts.get(cat)
        if not isinstance(items, list):
            continue
        if cat == "notes":
            seen = {_ctx_norm(n) for n in out["notes"] if isinstance(n, str)}
            for n in items:
                if isinstance(n, str) and _ctx_norm(n) and _ctx_norm(n) not in seen:
                    out["notes"].append(n)
                    seen.add(_ctx_norm(n))
            continue
        index = {}
        for i, it in enumerate(out[cat]):
            ident = _ctx_identity(cat, it)
            if ident:
                index[ident] = i
        for it in items:
            ident = _ctx_identity(cat, it)
            if not ident or ident == "|":
                continue
            if ident in index:
                target = out[cat][index[ident]]  # update in place; non-empty new values win
                for f, v in it.items():
                    if v not in (None, "", []):
                        target[f] = v
            else:
                out[cat].append(it)
                index[ident] = len(out[cat]) - 1

    # --- Apply removals (explicit only: resolved/done/cancelled) ---
    for cat in _CTX_LIST_FIELDS:
        rem = removals.get(cat)
        if not isinstance(rem, list) or not rem:
            continue
        if cat == "notes":
            remset = {_ctx_norm(r) for r in rem if isinstance(r, str)}
            out["notes"] = [n for n in out["notes"] if _ctx_norm(n) not in remset]
            continue
        remset = set()
        for r in rem:
            if isinstance(r, str):
                remset.add(_ctx_norm(r))
            elif isinstance(r, dict):
                remset.add(_ctx_identity(cat, r))
        remset.discard("")
        out[cat] = [it for it in out[cat] if _ctx_identity(cat, it) not in remset]

    # --- Soft cap (keep most-recent; only guards runaway growth) ---
    for cat in _CTX_LIST_FIELDS:
        if len(out[cat]) > _CTX_CAP:
            out[cat] = out[cat][-_CTX_CAP:]

    return out


class BackgroundTasksMixin:
    """Mixin for background task management (summarization, profile extraction)."""

    def _run_suggestions_thread(self, message_id: str, user_prompt: str, ai_response: str):
        """Generate follow-up suggestions off the request path and persist them.
        Uses the sync Groq client (safe in a thread); the frontend polls the
        audit endpoint and injects them once written."""
        try:
            s_p = self._get_follow_up_suggestions(user_prompt=user_prompt, ai_response=ai_response)
            if s_p:
                db.update_suggested_prompts(message_id, s_p)
        except Exception as e:
            self.log.warning(f"Background follow-up suggester failed: {e}")

    def _run_summarization_thread(self, conversation_id: str, old_summary: str, user_prompt: str, ai_response: str):
        """Runs the summarization logic in a background thread (provider-routed
        via _backend_completion, so it follows SUMMARIZER_MODEL to any provider)."""
        summarizer_prompt_config = self.prompts.get("summarizer")
        if not summarizer_prompt_config: return

        try:
            system_prompt = summarizer_prompt_config["system_prompt"]
            content = (f"PREVIOUS MEMORY:\n{old_summary if old_summary else 'No history.'}\n\n" f"LATEST EXCHANGE:\nUser: {user_prompt}\nAI: {ai_response}\n\nUPDATED MEMORY:")

            summary = self._backend_completion(
                system_prompt, content,
                model=getattr(self.config, "SUMMARIZER_MODEL", None),
                temperature=0.0, json_mode=False,
            )
            if summary:
                db.update_conversation_summary(conversation_id, summary)
        except Exception as e:
            self.log.warning(f"Summarization thread failed: {e}")

    def _run_profile_update_thread(self, user_id: str, current_profile_json: str, user_prompt: str, ai_response: str):
        """Runs the long-term user profile update logic in a background thread
        (provider-routed via _backend_completion)."""
        profile_prompt_config = self.prompts.get("profile_extractor")
        if not profile_prompt_config: return

        try:
            system_prompt = profile_prompt_config["system_prompt"]
            content = (
                f"CURRENT_PROFILE_JSON:\n{current_profile_json}\n\n"
                f"LATEST_EXCHANGE:\nUser: {user_prompt}\nAI: {ai_response}\n\n"
                "Return the new, updated JSON object."
            )
            profile = self._backend_completion(
                system_prompt, content,
                model=getattr(self.config, "SUMMARIZER_MODEL", None),
                temperature=0.0, json_mode=True,
            )
            if profile:
                db.upsert_user_profile_memory(user_id, profile)
                self.log.info(f"Successfully updated user profile for {user_id}")
        except Exception as e:
            self.log.warning(f"User profile update thread failed: {e}")

    def _get_backend_sync_client(self, provider: str):
        """
        Lazily builds and caches a synchronous client for the given provider, from
        the same provider config the LLMProvider uses (build_providers_config), so
        background threads can reach every provider the faculties can. Returns
        None when the provider has no API key configured. Gemini is excluded —
        its google-genai client is already sync-capable and shared via self.clients.
        """
        cache = getattr(self, "_backend_sync_clients", None)
        if cache is None:
            cache = self._backend_sync_clients = {}
        if provider in cache:
            return cache[provider]

        from ..services.model_routing import build_providers_config
        details = build_providers_config(self.config).get(provider)
        client = None
        if details and details.get("api_key"):
            try:
                if details["type"] == "openai":
                    from openai import OpenAI
                    client = OpenAI(api_key=details["api_key"], base_url=details.get("base_url"))
                elif details["type"] == "anthropic":
                    from anthropic import Anthropic
                    client = Anthropic(api_key=details["api_key"])
            except Exception as e:
                self.log.warning(f"[Backend] sync client init failed for '{provider}': {e}")
        cache[provider] = client
        return client

    def _backend_completion(self, system_prompt: str, user_content: str, model: str | None = None,
                            temperature: float | None = None, json_mode: bool = True):
        """
        Synchronous completion for background tasks (summaries, note-taker,
        suggestions), routed to whichever provider serves `model` — any provider
        the faculties support works here too. Returns raw model text, or None.

        json_mode enables native JSON constraints where the API supports them
        (OpenAI-compatible response_format / Gemini response_mime_type); Anthropic
        has no equivalent, so it gets a system-prompt instruction instead and
        callers' fence-tolerant parsers handle the rest.

        model defaults to BACKEND_MODEL (general-purpose); the note-taker passes
        NOTETAKER_MODEL, the summarizer SUMMARIZER_MODEL. temperature defaults to
        AGENT_MEMORY_TEMPERATURE; callers that want variety pass their own.
        """
        if model is None:
            model = self.config.BACKEND_MODEL
        if temperature is None:
            temperature = self.config.AGENT_MEMORY_TEMPERATURE
        # Per-org provider governance, asserted on the provider that actually
        # receives content. Background conveniences degrade gracefully: skip,
        # never reroute.
        provider = detect_provider(model)
        try:
            assert_provider_allowed(provider, context=f"backend:{model}")
        except ProviderNotAllowedError as e:
            self.log.warning(f"[Governance] Background completion skipped: {e}")
            return None
        try:
            if provider == "gemini":
                client = getattr(self, "clients", {}).get("gemini")
                if client is None:
                    self.log.warning("[Backend] gemini client unavailable; skipping.")
                    return None
                from google.genai import types as _gtypes
                cfg = _gtypes.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                    response_mime_type="application/json" if json_mode else None,
                )
                resp = client.models.generate_content(model=model, contents=user_content, config=cfg)
                return (getattr(resp, "text", "") or "").strip()

            if provider == "anthropic":
                client = self._get_backend_sync_client("anthropic")
                if client is None:
                    self.log.warning("[Backend] anthropic client unavailable; skipping.")
                    return None
                system = system_prompt
                if json_mode:
                    system += "\n\nRespond with only the valid JSON object — no prose, no code fences."
                resp = client.messages.create(
                    model=model,
                    max_tokens=4096,
                    system=system,
                    messages=[{"role": "user", "content": user_content}],
                    temperature=temperature,
                )
                text = "".join(
                    b.text for b in resp.content if getattr(b, "type", "") == "text"
                ).strip()
                if json_mode:
                    # No native JSON mode: the model may fence the object anyway,
                    # and some callers parse with plain json.loads — trim to the
                    # outermost braces so they always get a bare object.
                    start, end = text.find("{"), text.rfind("}")
                    if start != -1 and end > start:
                        text = text[start:end + 1]
                return text

            # OpenAI-compatible providers (Groq, OpenAI, DeepSeek, Mistral, Zhipu, Cerebras)
            client = self._get_backend_sync_client(provider)
            if client is None:
                self.log.warning(f"[Backend] {provider} client unavailable; skipping.")
                return None
            params = {
                "model": model,
                "messages": [{"role": "system", "content": system_prompt},
                             {"role": "user", "content": user_content}],
                "temperature": temperature,
            }
            if json_mode:
                params["response_format"] = {"type": "json_object"}
            resp = client.chat.completions.create(**params)
            return resp.choices[0].message.content.strip()
        except Exception as e:
            self.log.warning(f"[Backend] completion failed ({model}): {e}")
            return None

    def _backend_json_completion(self, system_prompt: str, user_content: str, model: str | None = None, temperature: float | None = None):
        """JSON-mode wrapper kept for existing callers (note-taker, suggestions)."""
        return self._backend_completion(system_prompt, user_content, model=model,
                                        temperature=temperature, json_mode=True)

    def _extract_agent_context_raw(self, current_context_json: str, user_prompt: str, ai_response: str):
        """
        Single extraction call. Returns the model's raw candidate-context string, or
        None on failure. Runs on NOTETAKER_MODEL (provider-routed via _backend_json_completion).
        """
        context_prompt_config = self.prompts.get("agent_context_extractor")
        if not context_prompt_config:
            return None
        content = (
            f"CURRENT_CONTEXT_JSON:\n{current_context_json}\n\n"
            f"LATEST_EXCHANGE:\nUser: {user_prompt}\nAI: {ai_response}\n\n"
            "Return the updated JSON object."
        )
        return self._backend_json_completion(
            context_prompt_config["system_prompt"], content, model=self.config.NOTETAKER_MODEL
        )

    def _run_agent_context_update_thread(self, user_id: str, agent_id: str, current_context_json: str, user_prompt: str, ai_response: str):
        """
        Runs the per-agent work context memory update in a background thread.
        Extracts only explicitly stated, durable, work-relevant facts — no inference.

        The model's output is treated as CANDIDATE facts and merged into the existing
        context in code (merge_agent_context), so an under-performing extraction can never
        drop previously-stored projects/people/tasks (anti-shrink). Invalid model JSON
        leaves the stored memory unchanged rather than overwriting it with garbage.
        """
        raw = self._extract_agent_context_raw(current_context_json, user_prompt, ai_response)
        if raw is None:
            return
        try:
            current = _json.loads(current_context_json) if current_context_json and current_context_json not in ("{}", "null", "") else {}
        except Exception:
            current = {}
        try:
            delta = _json.loads(raw)
        except Exception:
            # Unparseable extractor output: leave stored memory untouched (anti-corruption).
            self.log.warning("[AgentMemory] extractor returned non-JSON; leaving memory unchanged.")
            return
        try:
            merged = merge_agent_context(current, delta)
            db.upsert_agent_context_memory(user_id, agent_id, _json.dumps(merged, ensure_ascii=False))
            self.log.info(f"[AgentMemory] Updated context for user={user_id} agent={agent_id}")
        except Exception as e:
            self.log.warning(f"[AgentMemory] Agent context merge/save failed: {e}")