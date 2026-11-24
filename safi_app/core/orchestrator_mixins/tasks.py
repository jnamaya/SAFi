from __future__ import annotations
import json as _json
import re as _re
from datetime import date as _date
from ...persistence import database as db
from ...config import Config
from ..services.model_routing import detect_provider
from ..services.provider_governance import assert_provider_allowed, ProviderNotAllowedError


def _record_backend_usage(provider, model, resp):
    from ..services.usage_tracking import extract_usage, record_usage
    shape = provider if provider in ("anthropic", "gemini") else "openai"
    usage = extract_usage(shape, resp)
    if usage:
        record_usage("background", provider, model, usage[0], usage[1])


_CTX_LIST_FIELDS = ["projects", "tasks", "decisions", "people", "milestones", "vendors", "notes"]
_CTX_ID_FIELD = {
    "projects": "name",
    "tasks": "task",
    "decisions": "question",
    "people": "name",
    "vendors": "name",
}
_CTX_CAP = 40


def _ctx_norm(s) -> str:
    return (s or "").strip().lower() if isinstance(s, str) else ""


def _ctx_identity(cat: str, item) -> str:
    if not isinstance(item, dict):
        return ""
    if cat == "milestones":
        return _ctx_norm(item.get("event")) + "|" + _ctx_norm(item.get("date"))
    return _ctx_norm(item.get(_CTX_ID_FIELD.get(cat, "")))


def merge_agent_context(current: dict, delta: dict, stamp: dict | None = None) -> dict:
    current = current if isinstance(current, dict) else {}
    out = {k: list(current.get(k) or []) for k in _CTX_LIST_FIELDS}

    if isinstance(delta, dict) and ("upserts" in delta or "removals" in delta):
        upserts = delta.get("upserts") or {}
        removals = delta.get("removals") or {}
    elif isinstance(delta, dict):
        upserts = {k: delta.get(k) for k in _CTX_LIST_FIELDS if k in delta}
        removals = {}
    else:
        upserts, removals = {}, {}

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
                target = out[cat][index[ident]]
                changed = False
                for f, v in it.items():
                    if v not in (None, "", []) and target.get(f) != v:
                        target[f] = v
                        changed = True
                if changed and stamp:
                    target.update(stamp)
            else:
                if stamp:
                    it = {**it, **stamp}
                out[cat].append(it)
                index[ident] = len(out[cat]) - 1

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

    for cat in _CTX_LIST_FIELDS:
        if len(out[cat]) > _CTX_CAP:
            if cat == "notes":
                out[cat] = out[cat][-_CTX_CAP:]
                continue
            ranked = sorted(
                range(len(out[cat])),
                key=lambda i: (str(out[cat][i].get("updated") or ""), i),
            )
            keep = set(ranked[-_CTX_CAP:])
            out[cat] = [it for i, it in enumerate(out[cat]) if i in keep]

    return out


def apply_memory_budget(context_json: str, max_chars: int) -> str:
    if not context_json or max_chars <= 0 or len(context_json) <= max_chars:
        return context_json
    try:
        parsed = _json.loads(context_json)
        if not isinstance(parsed, dict):
            return context_json
        dropped = 0
        def _size(obj) -> int:
            return len(_json.dumps(obj, ensure_ascii=False))
        while _size(parsed) > max_chars:
            cat = max(
                (c for c in _CTX_LIST_FIELDS if isinstance(parsed.get(c), list) and parsed[c]),
                key=lambda c: len(parsed[c]),
                default=None,
            )
            if cat is None:
                break
            parsed[cat].pop(0)
            dropped += 1
            parsed["truncation_notice"] = (
                f"{dropped} older item(s) omitted to fit the memory budget; "
                "ask the user rather than guessing about older work."
            )
        return _json.dumps(parsed, ensure_ascii=False)
    except Exception:
        return context_json


class BackgroundTasksMixin:
    @staticmethod
    def _clean_title(raw):
        if not raw or not str(raw).strip():
            return None
        t = str(raw).strip().splitlines()[0].strip()
        t = _re.sub(r'^\s*title\s*[:\-]\s*', '', t, flags=_re.I)
        t = t.strip('\'"“”‘’` ').strip()
        t = _re.sub(r'\s+', ' ', t)
        t = t.rstrip('.…').strip()
        if not t:
            return None
        if len(t) > 70:
            return None
        return t

    def _run_title_thread(self, conversation_id, user_prompt, ai_response, initial_title):
        try:
            raw = self._backend_completion(
                "You name conversations. Reply with the title only — no quotes, no explanation.",
                "Write a concise title (3-6 words) for this conversation, in the same "
                "language the user wrote in. No quotes, no trailing period.\n\n"
                f"User: {(user_prompt or '')[:400]}\n"
                f"Assistant: {(ai_response or '')[:400]}",
                temperature=0.2, json_mode=False)
            title = self._clean_title(raw)
            if not title or title == initial_title:
                return
            current = db.get_conversation_title(conversation_id)
            if current is not None and current != initial_title:
                return
            db.rename_conversation(conversation_id, title)
        except Exception as e:
            self.log.warning(f"Background title generation failed: {e}")

    def _run_summarization_thread(self, conversation_id: str, old_summary: str, user_prompt: str, ai_response: str):
        summarizer_prompt_config = self.application_prompts.get("summarizer")
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
        profile_prompt_config = self.application_prompts.get("profile_extractor")
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

    def _get_backend_sync_client(self, provider: str, model: str | None = None):
        cache = getattr(self, "_backend_sync_clients", None)
        if cache is None:
            cache = self._backend_sync_clients = {}

        from ..services.model_routing import build_providers_config
        from ..services.deployment_keys import resolve_provider_key
        details = dict(build_providers_config(self.config).get(provider) or {})
        if provider == "local":
            conscience_url = (getattr(self.config, "CONSCIENCE_BASE_URL", "") or "").strip()
            conscience_model = (getattr(self.config, "CONSCIENCE_MODEL", "") or "").strip()
            if conscience_url and (
                (model and conscience_model and model == conscience_model)
                or "conscience" in (model or "").lower()
            ):
                details["base_url"] = conscience_url
        api_key = resolve_provider_key(provider, details.get("api_key"))
        base_url = details.get("base_url")
        cache_key = (provider, api_key, base_url)
        if cache_key in cache:
            return cache[cache_key]

        client = None
        if details and api_key:
            try:
                if details["type"] == "openai":
                    from openai import OpenAI
                    client = OpenAI(api_key=api_key, base_url=base_url)
                elif details["type"] == "anthropic":
                    from anthropic import Anthropic
                    client = Anthropic(api_key=api_key)
            except Exception as e:
                self.log.warning(f"[Backend] sync client init failed for '{provider}': {e}")
        cache[cache_key] = client
        return client

    def _backend_completion(self, system_prompt: str, user_content: str, model: str | None = None,
                            temperature: float | None = None, json_mode: bool = True):
        if model is None:
            model = self.config.BACKEND_MODEL
        if temperature is None:
            temperature = self.config.AGENT_MEMORY_TEMPERATURE
        provider = detect_provider(model)
        try:
            assert_provider_allowed(provider, context=f"backend:{model}")
        except ProviderNotAllowedError as e:
            self.log.warning(f"[Governance] Background completion skipped: {e}")
            return None
        try:
            if provider == "gemini":
                client = getattr(self, "clients", {}).get("gemini")
                from ..services.deployment_keys import resolve_provider_key
                from ..services.model_routing import build_providers_config
                env_gemini_key = (build_providers_config(self.config)
                                  .get("gemini") or {}).get("api_key")
                org_key = resolve_provider_key("gemini", env_gemini_key)
                if org_key and org_key != env_gemini_key:
                    cache = getattr(self, "_backend_sync_clients", None)
                    if cache is None:
                        cache = self._backend_sync_clients = {}
                    cache_key = ("gemini", org_key)
                    if cache_key not in cache:
                        try:
                            from google import genai as _genai
                            cache[cache_key] = _genai.Client(api_key=org_key)
                        except Exception as e:
                            self.log.warning(f"[Backend] gemini org-key client init failed: {e}")
                            cache[cache_key] = None
                    client = cache[cache_key] or client
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
                _record_backend_usage("gemini", model, resp)
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
                _record_backend_usage("anthropic", model, resp)
                text = "".join(
                    b.text for b in resp.content if getattr(b, "type", "") == "text"
                ).strip()
                if json_mode:
                    start, end = text.find("{"), text.rfind("}")
                    if start != -1 and end > start:
                        text = text[start:end + 1]
                return text

            client = self._get_backend_sync_client(provider, model=model)
            if client is None:
                self.log.warning(f"[Backend] {provider} client unavailable; skipping.")
                return None
            params = {
                "model": model,
                "messages": [{"role": "system", "content": system_prompt},
                             {"role": "user", "content": user_content}],
            }
            from ..services.llm_provider import _is_openai_flagship
            if not ("o1" in (model or "").lower() or "o3" in (model or "").lower() or _is_openai_flagship(model)):
                params["temperature"] = temperature
            if json_mode:
                params["response_format"] = {"type": "json_object"}
            resp = client.chat.completions.create(**params)
            _record_backend_usage(provider, model, resp)
            return resp.choices[0].message.content.strip()
        except Exception as e:
            self.log.warning(f"[Backend] completion failed ({model}): {e}")
            return None

    def _backend_json_completion(self, system_prompt: str, user_content: str, model: str | None = None, temperature: float | None = None):
        return self._backend_completion(system_prompt, user_content, model=model,
                                        temperature=temperature, json_mode=True)

    def _extract_agent_context_raw(self, current_context_json: str, user_prompt: str, ai_response: str):
        context_prompt_config = self.application_prompts.get("agent_context_extractor")
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

    def _run_agent_context_update_thread(self, user_id: str, agent_id: str, current_context_json: str, user_prompt: str, ai_response: str, message_id: str | None = None):
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
            self.log.warning("[AgentMemory] extractor returned non-JSON; leaving memory unchanged.")
            return
        try:
            stamp = {"updated": _date.today().isoformat()}
            if message_id:
                stamp["src"] = str(message_id)
            merged = merge_agent_context(current, delta, stamp=stamp)
            if _json.dumps(merged, sort_keys=True) == _json.dumps(
                    {k: current.get(k) or [] for k in _CTX_LIST_FIELDS}, sort_keys=True):
                return
            db.upsert_agent_context_memory(user_id, agent_id, _json.dumps(merged, ensure_ascii=False))
            self.log.info(f"[AgentMemory] Updated context for user={user_id} agent={agent_id}")
        except Exception as e:
            self.log.warning(f"[AgentMemory] Agent context merge/save failed: {e}")
