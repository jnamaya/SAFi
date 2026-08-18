"""
Defines the LLMProvider service.

This is the "Universal Client". It centralizes all API interactions.
It supports OpenAI, Anthropic, and Gemini natively, and generic OpenAI-compatible
providers (like DeepSeek, Groq, Mistral, Ollama) via configuration.
"""
from __future__ import annotations
import json
import logging
import asyncio
from typing import List, Dict, Any, Tuple, Optional

# External provider libraries
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
from google import genai
from google.genai import types

# Internal parsing utilities
from .parsing_utils import (
    parse_intellect_response,
    parse_will_response,
    parse_conscience_response
)

# The Conscience's sampling temperature is a governance parameter, not a
# transport one, so it is DEFINED in the Conscience faculty — a file covered by
# the Core Loop integrity manifest — and only consumed here. This module stays
# outside the manifest so organizations can add providers without a Section IV
# review; that same openness must not extend to quietly changing how strictly
# every agent in a deployment is audited. Full rationale at the definition.
from ..faculties.conscience import CONSCIENCE_TEMPERATURE  # noqa: F401  (re-exported)


class LLMProvider:
    """
    A unified service to handle all LLM calls.
    Faculties call this service by 'route' (e.g., 'intellect'), not by model name.
    """
    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: A dictionary defining providers and routes.
        """
        self.config = config
        self.log = logging.getLogger(self.__class__.__name__)
        self.clients = {}
        self._initialize_clients()

    def _initialize_clients(self):
        """Initializes API clients based on the provider config."""
        providers = self.config.get("providers", {})
        
        for name, details in providers.items():
            p_type = details.get("type")
            api_key = details.get("api_key")
            
            # Allow skipping provider if key is empty/None
            if not api_key:
                self.log.debug(f"Skipping provider '{name}': No API key provided.")
                continue

            try:
                if p_type == "openai":
                    self.clients[name] = AsyncOpenAI(
                        api_key=api_key,
                        base_url=details.get("base_url") # Handles Groq, DeepSeek, Mistral
                    )
                elif p_type == "anthropic":
                    self.clients[name] = AsyncAnthropic(api_key=api_key)
                elif p_type == "gemini":
                    self.clients[name] = genai.Client(api_key=api_key)
                else:
                    self.log.error(f"Unknown provider type '{p_type}' for '{name}'")
            except Exception as e:
                self.log.error(f"Failed to initialize provider '{name}': {e}")

    def _capture_usage(self, route, provider_name, model_name, provider_type, resp):
        """Record the call's token counts for the Usage & Cost tab (backlog 61).
        Attribution (org, agent) comes from context vars; failures are logged
        and swallowed inside usage_tracking — never a broken turn."""
        from .usage_tracking import extract_usage, record_usage
        usage = extract_usage(provider_type, resp)
        if usage:
            record_usage(route, provider_name, model_name, usage[0], usage[1])

    async def _chat_completion(
        self,
        route: str,
        system_prompt: str,
        user_prompt: Any,
        temperature: float = 1.0,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
        extra_body: Optional[Dict[str, Any]] = None,
        top_p: Optional[float] = None,
        json_mode: bool = False,
    ) -> str:
        """
        Internal generic handler that routes the request to the correct provider.

        json_mode constrains decoding to valid JSON at the API level (OpenAI-compatible
        response_format / Gemini response_mime_type). Callers must still instruct the
        model to produce JSON in the prompt — OpenAI-compatible providers reject json
        mode otherwise. Ignored when tools are passed (the two are incompatible) and
        on providers with no native support (Anthropic).
        """
        route_config = self.config.get("routes", {}).get(route)
        if not route_config:
            raise ValueError(f"No route configuration found for '{route}'")

        provider_name = route_config["provider"]
        model_name = route_config["model"]

        # Per-org provider governance — fail closed BEFORE any dispatch. No
        # active org context = unrestricted; a disallowed provider raises,
        # never reroutes (see provider_governance module docstring).
        from .provider_governance import assert_provider_allowed
        assert_provider_allowed(provider_name, context=f"route:{route}, model:{model_name}")

        # Get provider details
        provider_details = self.config.get("providers", {}).get(provider_name)
        if not provider_details:
             raise ValueError(f"Provider '{provider_name}' defined in route '{route}' not found in providers config.")

        provider_type = provider_details["type"]
        client = self.clients.get(provider_name)

        if not client:
            raise RuntimeError(f"Client for provider '{provider_name}' is not initialized. Check API Key.")

        # Serialize user_prompt to string for non-Gemini providers if it's a list (history array)
        user_prompt_str = user_prompt
        if isinstance(user_prompt, list) and provider_type != "gemini":
            str_parts = []
            for item in user_prompt:
                str_parts.append(str(item))
            user_prompt_str = "\n\n".join(str_parts)

        # --- Dispatch based on Type ---
        
        # 1. OpenAI / DeepSeek / Groq / Mistral
        if provider_type == "openai":
            params = {
                "model": model_name,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt_str},
                ]
            }
            if top_p is not None:
                params["top_p"] = top_p
            if extra_body is not None:
                params["extra_body"] = extra_body
            if json_mode and not tools:
                params["response_format"] = {"type": "json_object"}

            # Map generic MCP tools to OpenAI format if provided
            if tools:
                openai_tools = []
                for t in tools:
                    openai_tools.append({
                        "type": "function",
                        "function": {
                            "name": t["name"],
                            "description": t["description"],
                            "parameters": t["input_schema"]
                        }
                    })
                params["tools"] = openai_tools
                # If tools are present, we force auto or required? Default is auto.

            # Handle o1/o3 reasoning models
            if "o1" in model_name or "o3" in model_name:
                # o1 models do not support 'system' role in current API versions
                params["messages"] = [{"role": "user", "content": f"System Instruction: {system_prompt}\n\nUser Query: {user_prompt}"}]
                # o1 models do not support temperature
                params.pop("temperature", None)
                # o1 uses max_completion_tokens
                params.pop("max_tokens", None)
                params["max_completion_tokens"] = max_tokens
                # o1 preview doesn't support tools well yet, so maybe skip tools for o1?
                # For now let's leave it, it might just error if used.
            elif model_name.lower().startswith("gpt-5"):
                # OpenAI's gpt-5.x line. Verified against the live API on
                # 2026-07-30 with gpt-5.6-luna: the system role and
                # `response_format: json_object` both work, but `max_tokens`,
                # `top_p`, and ANY temperature other than the default all return
                # a hard 400. This is why the whole family was unusable — note
                # that gpt-5-mini and gpt-5-nano are the configured `openai`
                # route defaults (see DEFAULT_MODELS_BY_PROVIDER), so this path
                # was broken for them too, not just for newly added models.
                #
                # Gated on `startswith("gpt-5")` deliberately. provider_type
                # "openai" is shared with Groq, Cerebras, DeepSeek and Mistral,
                # and those must keep sending max_tokens. The prefix excludes
                # Groq's "openai/gpt-oss-*" (vendor-prefixed) and Cerebras'
                # "gpt-oss-*" without needing to know the provider here.
                #
                # CAVEAT, deliberately not worked around: forcing the default
                # temperature costs the Conscience its temperature=0.0
                # determinism if an operator selects a gpt-5.x model for that
                # route. That is the model's constraint, not ours, but it is a
                # governance-visible behaviour change.
                params.pop("temperature", None)
                params.pop("top_p", None)
                params["max_completion_tokens"] = max_tokens
                if params.get("tools"):
                    # Function tools are rejected on /v1/chat/completions unless
                    # reasoning is explicitly turned OFF. The error names
                    # reasoning_effort even when the caller never sent one,
                    # because the model applies a default. Probed 2026-07-30
                    # against gpt-5.6-luna: omitted / "low" / "medium" / "high"
                    # all 400; "minimal" is not a valid value for this model;
                    # only "none" is accepted, and it returns a proper
                    # tool_calls response.
                    #
                    # The trade-off is real and worth knowing: this buys tool
                    # calling by giving up the model's reasoning for that turn.
                    # Keeping tools AND reasoning requires the /v1/responses API,
                    # which is a port rather than a parameter change. Only sent
                    # when tools are actually present, so ordinary turns keep
                    # the model's default reasoning.
                    params["reasoning_effort"] = "none"
            else:
                 params["max_tokens"] = max_tokens

            resp = await client.chat.completions.create(**params)
            self._capture_usage(route, provider_name, model_name, provider_type, resp)

            # OpenAI Tool Use Handling
            msg = resp.choices[0].message
            if msg.tool_calls:
                # Return a special structure indicating tool call
                return json.dumps({
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "name": tc.function.name,
                            "arguments": json.loads(tc.function.arguments)
                        } for tc in msg.tool_calls
                    ]
                })

            return msg.content or "{}"

        # 2. Anthropic (Claude)
        elif provider_type == "anthropic":
            kwargs = {
                "model": model_name,
                "system": system_prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": user_prompt_str}]
            }

            if tools:
                anthropic_tools = []
                for t in tools:
                    anthropic_tools.append({
                        "name": t["name"],
                        "description": t["description"],
                        "input_schema": t["input_schema"]
                    })
                kwargs["tools"] = anthropic_tools

            resp = await client.messages.create(**kwargs)
            self._capture_usage(route, provider_name, model_name, provider_type, resp)

            # Check for tool use
            if resp.stop_reason == "tool_use":
                tool_calls = []
                for block in resp.content:
                    if block.type == "tool_use":
                        tool_calls.append({
                            "id": block.id,
                            "name": block.name,
                            "arguments": block.input
                        })
                return json.dumps({"tool_calls": tool_calls})

            # Check for text content
            text_content = ""
            for block in resp.content:
                if block.type == "text":
                    text_content += block.text
            
            return text_content or "{}"

        # 3. Google Gemini
        elif provider_type == "gemini":
            def convert_schema(schema_dict: Dict[str, Any]) -> types.Schema:
                if not schema_dict:
                    return types.Schema(type="OBJECT", properties={})
                schema_type = schema_dict.get("type", "object").upper()
                properties = {}
                for k, v in schema_dict.get("properties", {}).items():
                    properties[k] = convert_schema(v)
                
                items = None
                if "items" in schema_dict:
                    items = convert_schema(schema_dict["items"])
                    
                return types.Schema(
                    type=schema_type,
                    description=schema_dict.get("description"),
                    properties=properties if properties else None,
                    required=schema_dict.get("required"),
                    items=items,
                    enum=schema_dict.get("enum")
                )

            gemini_tools = None
            if tools:
                funcs = []
                for t in tools:
                    funcs.append(types.FunctionDeclaration(
                        name=t["name"],
                        description=t["description"],
                        parameters=convert_schema(t.get("input_schema", {}))
                    ))
                gemini_tools = [types.Tool(function_declarations=funcs)]

            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=temperature,
                max_output_tokens=max_tokens,
                tools=gemini_tools,
                response_mime_type="application/json" if (json_mode and not gemini_tools) else None,
            )

            try:
                # user_prompt can be a string or list of types.Content (history array)
                resp = await client.aio.models.generate_content(
                    model=model_name, 
                    contents=user_prompt, 
                    config=config
                )
            except Exception as e:
                self.log.error(f"Gemini generation failed: {e}")
                return "{}"
            self._capture_usage(route, provider_name, model_name, provider_type, resp)

            # --- GEMINI FIX: Safe Text Access & Tool Check ---
            try:
                if getattr(resp, 'function_calls', None):
                    fc = resp.function_calls[0]
                    # args is a dict or mapping depending on SDK
                    args = fc.args if isinstance(fc.args, dict) else (dict(fc.args) if fc.args else {})
                    
                    payload = {
                        "tool_calls": [{
                            "id": "gemini_call",
                            "name": fc.name,
                            "arguments": args
                        }]
                    }
                    if resp.candidates and resp.candidates[0].content:
                        raw_content = resp.candidates[0].content
                        
                        # Try to use mode='json' if available (Pydantic v2)
                        if hasattr(raw_content, "model_dump"):
                            try:
                                payload["_gemini_raw_turn"] = raw_content.model_dump(mode="json")
                            except TypeError:
                                payload["_gemini_raw_turn"] = raw_content.model_dump()
                        else:
                            payload["_gemini_raw_turn"] = dict(raw_content)
                    
                    def safe_serialize(obj):
                        if isinstance(obj, bytes):
                            return obj.decode('utf-8', errors='ignore')
                        return str(obj)
                        
                    return json.dumps(payload, default=safe_serialize)

                # Surface a truncated generation. Gemini stops with
                # finish_reason=MAX_TOKENS when the output (including thinking
                # tokens) exhausts max_output_tokens; resp.text still holds the
                # partial answer, so without this check it would silently reach
                # the user mid-sentence. Compare on the name to stay robust
                # across SDK enum/string representations.
                try:
                    if resp.candidates:
                        finish_reason = getattr(resp.candidates[0], "finish_reason", None)
                        if finish_reason is not None and "MAX_TOKENS" in str(finish_reason):
                            self.log.warning(
                                "Gemini Intellect response truncated (finish_reason=MAX_TOKENS); "
                                "answer was cut off mid-output. Consider raising max_output_tokens "
                                "or capping the thinking budget."
                            )
                except Exception:
                    pass

                return resp.text or "{}"
            except Exception as e:
                self.log.warning(f"Gemini returned empty response or error: {e}")
                return "{}"

        else:
            raise ValueError(f"Unsupported provider type '{provider_type}'")


    # --- Public Faculty Interfaces ---

    # Times to re-ask the Intellect model when it returns a blank/contentless
    # response. Fast models (e.g. *-flash) intermittently emit empty content,
    # which the provider surfaces as the "{}" sentinel; each attempt resamples
    # the model so a blank never reaches the user.
    _INTELLECT_MAX_ATTEMPTS = 3

    @staticmethod
    def explain_provider_error(exc: Exception) -> str:
        """Turn a provider exception into something an operator can act on.

        The provider layer knows exactly why a call failed — a 401 with
        'Invalid API Key' is unambiguous — but that detail used to be logged and
        then discarded, leaving the user with "LLM provider returned an empty
        response." True, and useless: it names a symptom and hides the cause.
        A first-time deployer reads it as "SAFi is broken" rather than "my key
        is wrong".
        """
        text = f"{type(exc).__name__}: {exc}"
        low = text.lower()
        if "401" in text or "invalid_api_key" in low or "authenticationerror" in low:
            return ("the model provider rejected the API key (HTTP 401). Set a valid key for "
                    "your provider in .env — GROQ_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, "
                    "GEMINI_API_KEY, MISTRAL_API_KEY, DEEPSEEK_API_KEY, CEREBRAS_API_KEY or "
                    "ZHIPU_API_KEY — then recreate the container (docker compose up -d) or "
                    "restart the service. A restart alone does not reload .env.")
        if "429" in text or "rate limit" in low or "ratelimit" in low:
            return ("the model provider rate-limited the request (HTTP 429). Wait and retry, "
                    "or switch to a model with more headroom.")
        if "404" in text or "model_not_found" in low or "does not exist" in low:
            return ("the provider does not recognise the configured model. Check the model "
                    "selected for this agent and SAFI_INTELLECT_MODEL in .env.")
        if any(k in low for k in ("connection", "timeout", "timed out", "resolve",
                                  "network", "unreachable", "getaddrinfo")):
            return ("the model provider could not be reached. Check outbound network access "
                    "from this host, and any proxy or firewall between it and the provider.")
        if "insufficient" in low or "quota" in low or "billing" in low:
            return ("the provider rejected the request for quota or billing reasons. Check the "
                    "account behind the configured API key.")
        return f"the model provider call failed — {text[:200]}"

    @staticmethod
    def _is_contentless_intellect_answer(answer: Optional[str]) -> bool:
        """True if the Intellect produced no real text (empty, or only the
        empty-content "{}" / "[]" sentinel)."""
        if not answer or not answer.strip():
            return True
        return answer.strip() in ("{}", "[]")

    async def run_intellect(self, system_prompt: str, user_prompt: Any, context_for_audit: str, tools: Optional[List[Dict[str, Any]]] = None) -> Tuple[str, str, str, Optional[Dict[str, Any]]]:
        """Runs the configured Intellect model and parses the result.

        Retries on a blank/contentless response so an empty model turn never
        reaches the user as a literal "{}". If every attempt is still blank,
        returns an empty answer so the caller's graceful empty-response path
        handles it instead of surfacing the sentinel.
        """
        last_exc: Optional[Exception] = None
        # Cleared per call so a stale cause from an earlier turn is never
        # reported against a later one.
        self.last_intellect_error: Optional[str] = None
        for attempt in range(1, self._INTELLECT_MAX_ATTEMPTS + 1):
            try:
                raw_content = await self._chat_completion(
                    route="intellect",
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=1.0,
                    # 8192 (up from 4096): the Intellect produces long, structured
                    # answers and runs on thinking models (e.g. gemini-3.6-flash)
                    # whose reasoning tokens also draw from this budget. 4096 was
                    # too tight and silently truncated answers mid-output.
                    max_tokens=8192,
                    tools=tools
                )
                raw_content_stripped = raw_content.strip() if raw_content else ""

                # A tool call is a valid (non-empty) response — return immediately,
                # never retried. Robust extraction for chatty models that wrap the
                # tool-call JSON in surrounding text.
                if '"tool_calls"' in raw_content_stripped:
                    start = raw_content_stripped.find('{')
                    end = raw_content_stripped.rfind('}')
                    if start != -1 and end != -1 and end > start:
                        json_text = raw_content_stripped[start:end+1]
                        try:
                            payload = json.loads(json_text)
                            if "tool_calls" in payload:
                                raw_turn = payload.get("_gemini_raw_turn")
                                return json_text, "Tool Call", context_for_audit, raw_turn
                        except:
                            pass

                parsed = parse_intellect_response(raw_content, self.log)
                answer, reflection = parsed[0], parsed[1]
                raw_turn = parsed[2] if len(parsed) > 2 else None

                if self._is_contentless_intellect_answer(answer):
                    self.log.warning(
                        "Intellect returned a blank/contentless response "
                        "(attempt %d/%d); retrying.", attempt, self._INTELLECT_MAX_ATTEMPTS
                    )
                    continue

                return answer, reflection, context_for_audit, raw_turn
            except Exception as e:
                last_exc = e
                self.log.exception(
                    "Intellect execution failed (attempt %d/%d)", attempt, self._INTELLECT_MAX_ATTEMPTS
                )
                continue

        # All attempts failed. On a hard error, preserve the legacy failure
        # contract (None); on persistent blanks, return an empty answer so the
        # caller shows its graceful empty-response message, never a literal "{}".
        if last_exc is not None:
            # Preserve WHY, so the Intellect can report a cause rather than a
            # symptom. Read by IntellectEngine when the answer comes back None.
            self.last_intellect_error = self.explain_provider_error(last_exc)
            return None, None, context_for_audit, None
        self.log.error("Intellect returned blank after %d attempts.", self._INTELLECT_MAX_ATTEMPTS)
        return "", "", context_for_audit, None

    async def run_will(self, system_prompt: str, user_prompt: str) -> Tuple[str, str]:
        """Runs the configured Will model and parses the result."""
        try:
            raw_content = await self._chat_completion(
                route="will",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.0,
                max_tokens=1024
            )
            decision, reason = parse_will_response(raw_content, self.log)
            return decision, reason
        except Exception as e:
            self.log.exception("Will execution failed")
            return "violation", f"System Error: {e}"

    async def run_conscience(self, system_prompt: str, user_prompt: str) -> List[Dict[str, Any]]:
        """Runs the configured Conscience model and parses the result.

        Model-agnostic by design. The Conscience route is whatever the operator
        configured, and this method must not know or care which model that is:
        per-model tuning here silently changes how strictly every agent in the
        deployment is audited, based on a substring match nobody reviewed. If a
        model needs a different request *shape* to be callable at all, that
        belongs in _chat_completion with the other provider adapters — it is an
        API constraint, not an audit policy.
        """
        try:
            ledger: List[Dict[str, Any]] = []
            try:
                # Constrain decoding to valid JSON at the API level: eliminates the
                # markdown-fence/prose failure class that otherwise degrades the
                # ledger and burns the orchestrator's re-audit retry.
                raw_content = await self._chat_completion(
                    route="conscience",
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=CONSCIENCE_TEMPERATURE,
                    max_tokens=8192,
                    json_mode=True,
                )
                ledger = parse_conscience_response(raw_content, self.log)
                if ledger:
                    return ledger
                # An empty ledger from a successful json_mode call is the
                # degenerate-output case (a bare "{}"), not a real audit — fall
                # through to the unconstrained retry. This is the generic form of
                # what used to be a "gemma" name check: the models that degenerate
                # under json_mode are caught by observing the empty result rather
                # than by guessing from the model id, at the cost of one wasted
                # call on those models.
                self.log.warning("Conscience json_mode returned an empty/unusable ledger; retrying without json_mode.")
            except Exception as e:
                # A provider that rejects json_mode would otherwise fail BOTH audit
                # attempts and brick the agent into permanent fail-closed. Retry
                # once without it; the text parser still handles unconstrained output.
                self.log.warning(f"Conscience json_mode call failed ({e}); retrying without json_mode.")

            raw_content = await self._chat_completion(
                route="conscience",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=CONSCIENCE_TEMPERATURE,
                max_tokens=8192,
            )
            return parse_conscience_response(raw_content, self.log)
        except Exception as e:
            self.log.exception("Conscience execution failed")
            return []