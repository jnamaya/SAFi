"""
Mixin for background task management (summarization, profile extraction).
"""
from __future__ import annotations
import json as _json
from ...persistence import database as db
from ...config import Config
from ..services.model_routing import detect_provider


def _norm(s) -> str:
    return " ".join(str(s).strip().lower().split())


def _empty_context() -> dict:
    return {k: [] for k in Config.AGENT_MEMORY_SCHEMA}


def merge_agent_context(existing_json: str, candidate_json: str) -> str:
    """
    Merge the extractor's candidate output INTO the existing context without ever
    dropping what was already stored (anti-shrink). The existing context is the base;
    candidate items are only ADDED (new) or used to refresh fields of a matching item.

    - Unparseable / non-dict candidate -> existing is returned unchanged (anti-corruption).
    - List-of-strings keys: union with case-insensitive dedupe.
    - List-of-dicts keys: dedupe by identity field; matching items get non-empty fields refreshed.
    - Each list capped at Config.AGENT_MEMORY_MAX_ITEMS_PER_KEY (keeps the most recent tail) to bound growth.
    """
    try:
        existing = _json.loads(existing_json) if existing_json and existing_json not in ("{}", "null", "") else {}
    except Exception:
        existing = {}
    if not isinstance(existing, dict):
        existing = {}

    merged = _empty_context()
    for k in Config.AGENT_MEMORY_SCHEMA:
        v = existing.get(k)
        if isinstance(v, list):
            merged[k] = list(v)

    try:
        candidate = _json.loads(candidate_json)
    except Exception:
        candidate = None
    if not isinstance(candidate, dict):
        # Anti-corruption guard: never overwrite good memory with garbage.
        return _json.dumps(merged, ensure_ascii=False)

    for key, idfield in Config.AGENT_MEMORY_SCHEMA.items():
        cand_items = candidate.get(key)
        if not isinstance(cand_items, list):
            continue
        if idfield is None:
            seen = {_norm(x) for x in merged[key] if isinstance(x, str)}
            for item in cand_items:
                if isinstance(item, dict):
                    item = item.get("note") or item.get("text") or _json.dumps(item, ensure_ascii=False)
                item = str(item)
                if _norm(item) and _norm(item) not in seen:
                    merged[key].append(item)
                    seen.add(_norm(item))
        else:
            index = {_norm(it[idfield]): i for i, it in enumerate(merged[key])
                     if isinstance(it, dict) and it.get(idfield)}
            for item in cand_items:
                if not isinstance(item, dict):
                    item = {idfield: str(item)}
                name = _norm(item.get(idfield, ""))
                if not name:
                    continue
                if name in index:
                    tgt = merged[key][index[name]]
                    for fk, fv in item.items():
                        if fv not in (None, "", []):
                            tgt[fk] = fv
                else:
                    merged[key].append(item)
                    index[name] = len(merged[key]) - 1

    for k in merged:
        if len(merged[k]) > Config.AGENT_MEMORY_MAX_ITEMS_PER_KEY:
            merged[k] = merged[k][-Config.AGENT_MEMORY_MAX_ITEMS_PER_KEY:]
    return _json.dumps(merged, ensure_ascii=False)


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
        """Runs the summarization logic in a background thread using Sync client."""
        if not hasattr(self, 'groq_client_sync') or not self.groq_client_sync:
            return
            
        summarizer_prompt_config = self.prompts.get("summarizer")
        if not summarizer_prompt_config: return

        try:
            system_prompt = summarizer_prompt_config["system_prompt"]
            content = (f"PREVIOUS MEMORY:\n{old_summary if old_summary else 'No history.'}\n\n" f"LATEST EXCHANGE:\nUser: {user_prompt}\nAI: {ai_response}\n\nUPDATED MEMORY:")
            
            response = self.groq_client_sync.chat.completions.create(
                model=getattr(self.config, "SUMMARIZER_MODEL", "llama-3.1-8b-instant"),
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": content}],
                temperature=0.0,
            )
            db.update_conversation_summary(conversation_id, response.choices[0].message.content.strip())
        except Exception as e:
            self.log.warning(f"Summarization thread failed: {e}")

    def _run_profile_update_thread(self, user_id: str, current_profile_json: str, user_prompt: str, ai_response: str):
        """Runs the long-term user profile update logic in a background thread."""
        if not hasattr(self, 'groq_client_sync') or not self.groq_client_sync:
            return

        profile_prompt_config = self.prompts.get("profile_extractor")
        if not profile_prompt_config: return

        try:
            system_prompt = profile_prompt_config["system_prompt"]
            content = (
                f"CURRENT_PROFILE_JSON:\n{current_profile_json}\n\n"
                f"LATEST_EXCHANGE:\nUser: {user_prompt}\nAI: {ai_response}\n\n"
                "Return the new, updated JSON object."
            )
            response = self.groq_client_sync.chat.completions.create(
                model=getattr(self.config, "SUMMARIZER_MODEL", "llama-3.1-8b-instant"),
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": content}],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            db.upsert_user_profile_memory(user_id, response.choices[0].message.content.strip())
            self.log.info(f"Successfully updated user profile for {user_id}")
        except Exception as e:
            self.log.warning(f"User profile update thread failed: {e}")

    def _backend_json_completion(self, system_prompt: str, user_content: str):
        """
        Synchronous JSON-returning completion on BACKEND_MODEL, routed by provider so
        background tasks aren't pinned to Groq. gemini-* models use the (sync-capable)
        google-genai client the LLMProvider already built; everything else uses the
        OpenAI-compatible sync client (Groq, etc.). Returns raw model text, or None.
        """
        model = self.config.BACKEND_MODEL
        temperature = self.config.AGENT_MEMORY_TEMPERATURE
        try:
            if detect_provider(model) == "gemini":
                client = getattr(self, "clients", {}).get("gemini")
                if client is None:
                    self.log.warning("[AgentMemory] gemini client unavailable; skipping update.")
                    return None
                from google.genai import types as _gtypes
                cfg = _gtypes.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                    response_mime_type="application/json",
                )
                resp = client.models.generate_content(model=model, contents=user_content, config=cfg)
                return (getattr(resp, "text", "") or "").strip()

            # Default: OpenAI-compatible sync client (Groq / DeepSeek / etc.)
            if not getattr(self, "groq_client_sync", None):
                return None
            resp = self.groq_client_sync.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system_prompt},
                          {"role": "user", "content": user_content}],
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            self.log.warning(f"[AgentMemory] backend completion failed ({model}): {e}")
            return None

    def _extract_agent_context_raw(self, current_context_json: str, user_prompt: str, ai_response: str):
        """
        Single extraction call. Returns the model's raw candidate-context string, or
        None on failure. Runs on BACKEND_MODEL (provider-routed via _backend_json_completion).
        """
        context_prompt_config = self.prompts.get("agent_context_extractor")
        if not context_prompt_config:
            return None
        content = (
            f"CURRENT_CONTEXT_JSON:\n{current_context_json}\n\n"
            f"LATEST_EXCHANGE:\nUser: {user_prompt}\nAI: {ai_response}\n\n"
            "Return the updated JSON object."
        )
        return self._backend_json_completion(context_prompt_config["system_prompt"], content)

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
            merged = merge_agent_context(current_context_json, raw)
            db.upsert_agent_context_memory(user_id, agent_id, merged)
            self.log.info(f"[AgentMemory] Updated context for user={user_id} agent={agent_id}")
        except Exception as e:
            self.log.warning(f"[AgentMemory] Agent context merge/save failed: {e}")