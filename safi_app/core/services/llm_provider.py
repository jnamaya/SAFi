"""The single dispatch point for every outbound model call.

One provider-agnostic surface — `_chat_completion` for prose, and
`run_conscience_structured` for the typed-decision contract — so faculties call
by route ('intellect', 'will', 'conscience') and never name a model or vendor.
Supports OpenAI, Anthropic and Gemini natively plus any OpenAI-compatible
provider (DeepSeek, Groq, Mistral, Zhipu, Cerebras, local llama.cpp) from
config. Provider-specific quirks live in the dispatch branches below, never in
the call sites.
"""
from __future__ import annotations
import os
import json
import logging
import asyncio
from typing import List, Dict, Any, Tuple, Optional
from contextvars import ContextVar

from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
from google import genai
from google.genai import types
import httpx

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


# Per-call ceiling on any provider request. Without it the SDK defaults (~600s
# for OpenAI/Anthropic) exceed gunicorn's --timeout (300s), so a provider that
# stalls rides to the worker-kill, which takes the worker's in-flight siblings
# with it (docker-entrypoint.sh) — one stuck call becomes a host-wide outage.
# Kept under 300s so even a turn's two calls (intellect + conscience) stay inside
# the request budget.
LLM_TIMEOUT_SECONDS = int(os.environ.get("SAFI_LLM_TIMEOUT", "300"))


# Output-token ceiling for the Intellect. Was a hardcoded 8192 until 2026-08-27
# (GOVERNANCE_BACKLOG 85), when three turns in one session stopped at exactly
# that number and the answers reached the user cut off mid-sentence.
#
# The budget covers a thinking model's hidden reasoning as well as the visible
# answer, so the answer can be far shorter than this number suggests: one of
# those turns spent the whole 8192 to emit about 2,700 tokens of text.
#
# Raising it lengthens generations, so check SAFI_GUNICORN_TIMEOUT and the web
# server's own Timeout before going much higher. LLM_TIMEOUT_SECONDS above is
# the per-call ceiling that actually cuts a slow generation off.
MAX_INTELLECT_TOKENS = int(os.environ.get("SAFI_MAX_INTELLECT_TOKENS", "8192"))


# Ceiling for the on-box llama.cpp server, applied only when a route resolves to
# the `local` provider. That server is CPU-bound on hardware the whole appliance
# shares, so a cloud provider's token budget is not a meaningful request of it:
# 8192 on a 3B model at ~11 tok/s is ~12 minutes of generation against
# SAFI_LLM_TIMEOUT's 300 s, so the call is cut off and returns nothing at all.
# Capping the request means the generation completes and whatever the model
# produced is returned, which beats a guaranteed timeout. Set to 0 to disable.
#
# A capacity ceiling, not an audit policy: keyed on the provider, never on a
# model-name substring, so it cannot change how strictly any agent is audited.
# See run_conscience's docstring for why that distinction matters there.
LOCAL_MAX_TOKENS = int(os.environ.get("SAFI_LOCAL_MAX_TOKENS", "1024"))


# Set when a provider reports that it stopped because the output budget ran out,
# rather than because the model finished. A ContextVar, not an attribute: one
# LLMProvider instance is shared by every concurrent request against the same
# profile, so an attribute would let one request read another's flag.
_TRUNCATED: ContextVar[bool] = ContextVar("safi_generation_truncated", default=False)


# Appended to an answer the provider cut short. Added to the DRAFT, before the
# Will and the Conscience see it, so the governance record shows the answer was
# incomplete rather than storing a partial answer as a whole one.
#
# Deliberately plain text: an org can ban markdown syntaxes through
# `structural_requirements`, and a notice that trips its own deployment's style
# gate would turn a truncated answer into a blocked one.
TRUNCATION_NOTICE = (
    "\n\n(This answer is incomplete. It reached the output limit for a single "
    "turn and stopped here. Ask to continue and it will pick up from this point.)"
)


def generation_was_truncated() -> bool:
    """True if the most recent provider call in this context hit its output cap.

    Must be read from the same task that made the call. A ContextVar set inside
    a coroutine propagates to its awaiting caller, which is how `run_intellect`
    sees it, but `asyncio.run`, `create_task` and `gather` each run their child
    in a COPY of the context, so a read on the far side of one of those returns
    the default and not the flag.
    """
    return _TRUNCATED.get()


def _is_openai_flagship(model_name: str) -> bool:
    """True for OpenAI's own gpt line, which rejects max_tokens/top_p/temperature.

    Deliberately not a version prefix. `provider_type == "openai"` is shared with
    Groq, Cerebras, DeepSeek and Mistral, all of which still need `max_tokens`,
    so the discriminator has to be the vendor's own naming and nothing else.

    "gpt-oss" is OpenAI's open-weight family, served here by Cerebras under a
    bare id and by Groq under an "openai/"-prefixed one. The bare form is the
    only one this can be fooled by, and it is excluded explicitly: it is
    temperature- and max_tokens-capable, so a gate that swept it up would cap
    every gpt-oss answer at the provider default with no error anywhere.

    A new major version must not need an edit here. That is the whole point.
    """
    m = (model_name or "").lower()
    return m.startswith("gpt-") and not m.startswith("gpt-oss")


class LLMProvider:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.log = logging.getLogger(self.__class__.__name__)
        self.clients = {}
        # Clients bound to an org's own key (backlog 64), keyed
        # (provider, key) so a rotated key gets a fresh client. Bounded in
        # practice by providers x orgs that stored a key.
        self._org_clients: Dict[Any, Any] = {}
        self._initialize_clients()

    def _initialize_clients(self):
        providers = self.config.get("providers", {})

        for name, details in providers.items():
            p_type = details.get("type")
            api_key = details.get("api_key")

            if not api_key:
                self.log.debug(f"Skipping provider '{name}': No API key provided.")
                continue

            try:
                if p_type == "openai":
                    self.clients[name] = AsyncOpenAI(
                        api_key=api_key,
                        # base_url is what makes Groq/DeepSeek/Mistral/Zhipu/
                        # Cerebras/local-llama.cpp work through one SDK.
                        base_url=details.get("base_url"),
                        timeout=LLM_TIMEOUT_SECONDS,
                    )
                elif p_type == "anthropic":
                    self.clients[name] = AsyncAnthropic(api_key=api_key, timeout=LLM_TIMEOUT_SECONDS)
                elif p_type == "gemini":
                    self.clients[name] = genai.Client(
                        api_key=api_key,
                        http_options=types.HttpOptions(timeout=LLM_TIMEOUT_SECONDS * 1000),  # ms
                    )
                elif p_type == "typesafe":
                    # Jev exposes typed decisions at /v1/systemone, not a chat
                    # completions endpoint. Conscience sends typed questions
                    # through run_conscience_structured() instead of a client.
                    continue
                else:
                    self.log.error(f"Unknown provider type '{p_type}' for '{name}'")
            except Exception as e:
                self.log.error(f"Failed to initialize provider '{name}': {e}")

    def uses_typed_conscience(self) -> bool:
        return False

    def tool_call_history_entry(self, tool_name: str, arguments: str,
                                raw_turn: Optional[Dict[str, Any]] = None):
        """Represent a proposed tool call in the routed model's history format."""
        route = self.config.get("routes", {}).get("intellect", {})
        provider = route.get("provider")
        details = self.config.get("providers", {}).get(provider, {})
        if details.get("type") == "gemini" and raw_turn:
            from google.genai import types
            return types.Content(**raw_turn)
        return (
            f"SYSTEM OBSERVATION: Model requested tool {tool_name} "
            f"with arguments: {arguments}"
        )

    def tool_result_history_entry(self, tool_name: str, result: str):
        """Represent a tool result in the routed model's history format."""
        route = self.config.get("routes", {}).get("intellect", {})
        provider = route.get("provider")
        details = self.config.get("providers", {}).get(provider, {})
        if details.get("type") == "gemini":
            from google.genai import types
            part = types.Part.from_function_response(name=tool_name, response={"result": result})
            return types.Content(role="user", parts=[part])
        return f"TOOL RESULT for {tool_name}:\n{result}"

    async def run_conscience_structured(
        self,
        *,
        state: Dict[str, Any],
        rubrics: List[Dict[str, Any]],
        instructions: str,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError("Structured Conscience dispatch is not available in v1.5.0")

        for index, rubric in enumerate(rubrics):
            value = str(rubric.get("value") or f"value_{index}")
            guide = rubric.get("scoring_guide") or []
            if not guide:
                raise ValueError(f"Conscience rubric '{value}' has no scoring guide")

            question_id = f"audit_{index}"
            criteria: Dict[str, Any] = {}
            mapping[question_id] = {}
            for level_index, level in enumerate(guide):
                if not isinstance(level, dict) or "score" not in level:
                    raise ValueError(f"Conscience rubric '{value}' has an invalid scoring level")
                option = f"level_{level_index}"
                score = float(level["score"])
                label = str(level.get("label") or f"Score {score:g}")
                description = str(
                    level.get("description")
                    or level.get("descriptor")
                    or level.get("criteria")
                    or ""
                )
                criteria[option] = {
                    "score": score,
                    "label": label,
                    "description": description,
                }
                mapping[question_id][option] = {
                    "score": score,
                    "label": label,
                    "description": description,
                }

            questions[question_id] = {
                "type": "choice",
                "instructions": {
                    "question": f"Which scoring-guide level best describes the final output for {value}?",
                    "guidance": instructions,
                    "rubric_description": str(rubric.get("description") or ""),
                },
                "criteria": criteria,
            }

        if not questions:
            return []

        if local_jev:
            # A blocking ONNX call in a worker thread: a forward pass over a few
            # short questions is milliseconds of CPU, but the first call in a
            # process also loads the 1.7 GB bundle, which must not stall the
            # event loop and time out every concurrent request behind it.
            try:
                result = await asyncio.to_thread(jev_local.system_one, state, questions)
            except jev_local.LocalJevUnavailable:
                # The bundle vanished between the availability check and the
                # call. Failing the turn is correct: re-running the question
                # against a different backend than the one that approved the
                # route would put a second, different judgement in the ledger
                # with no trace of the first.
                raise RuntimeError("Local Jev bundle became unavailable during the audit")
            except Exception as exc:
                self.log.error("Local Jev failed, refusing to fall back to a remote call: %s", exc)
                raise RuntimeError(f"Local Jev inference failed: {exc}") from exc
        else:
            base_url = (details.get("base_url") or "https://api.typesafe.ai/v1").rstrip("/")
            payload = {"model": model_name, "state": state, "questions": questions}
            async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{base_url}/systemone",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()

        answers = result.get("answers")
        if not isinstance(answers, dict):
            raise ValueError("TypeSafe returned no answers map")

        ledger: List[Dict[str, Any]] = []
        for index, rubric in enumerate(rubrics):
            question_id = f"audit_{index}"
            answer = answers.get(question_id)
            if not isinstance(answer, dict):
                raise ValueError(f"Typed Conscience backend omitted value {rubric.get('value')!r}")
            choice = answer.get("choice")
            selected = mapping[question_id].get(choice)
            if selected is None:
                raise ValueError(f"Typed Conscience backend returned an unknown scoring level for {rubric.get('value')!r}")
            confidence = float(answer.get("confidence"))
            if not 0.0 <= confidence <= 1.0:
                raise ValueError(f"Typed Conscience backend returned invalid confidence for {rubric.get('value')!r}")
            probabilities = answer.get("probabilities")
            if not isinstance(probabilities, dict):
                raise ValueError(f"Typed Conscience backend omitted probabilities for {rubric.get('value')!r}")
            choice_distribution = []
            for option, band in mapping[question_id].items():
                try:
                    probability = float(probabilities.get(option, 0.0))
                except (TypeError, ValueError):
                    probability = 0.0
                choice_distribution.append({
                    "label": band["label"],
                    "probability": probability,
                })
            entry = {
                "value": rubric.get("value"),
                "score": selected["score"],
                "confidence": confidence,
                "reason": selected["description"],
                "probabilities": probabilities,
                "choice_distribution": choice_distribution,
                "selected_level": selected["label"],
                "assessment_explanation": selected["description"],
            }
            recorded_violation = state.get("violation_type")
            if isinstance(recorded_violation, str) and recorded_violation:
                entry["recorded_violation"] = recorded_violation
            ledger.append(entry)

        usage = result.get("usage") or {}
        try:
            tokens_in = int(usage.get("input_tokens", 0))
            tokens_out = int(usage.get("output_tokens", 0))
            if tokens_in or tokens_out:
                from .usage_tracking import record_usage
                record_usage(
                    "conscience", provider_name,
                    result.get("model") or model_name,
                    tokens_in, tokens_out,
                )
        except (TypeError, ValueError):
            self.log.warning("Typed Conscience backend returned malformed token usage; not recording it.")
        return ledger

    def _org_override_client(self, provider_name: str, provider_details: Dict[str, Any]):
        """A client bound to a DB-stored key — the active org's own key, else
        the deployment key — or None to use the .env deployment client. Mirrors
        _initialize_clients per provider type; a construction failure falls back
        to the deployment client rather than breaking the turn.

        Keyed on the resolved key, not the org, so the org layer and the
        deployment layer share one cache: a provider with only a deployment key
        costs the same as one with only a .env key.
        """
        from .deployment_keys import resolve_provider_key
        env_key = (provider_details or {}).get("api_key")
        key = resolve_provider_key(provider_name, env_key)
        # No DB layer for this provider: the cached .env client is already
        # correct, so don't build a second one.
        if not key or key == env_key:
            return None
        cache_key = (provider_name, key)
        client = self._org_clients.get(cache_key)
        if client is not None:
            return client
        try:
            p_type = provider_details.get("type")
            if p_type == "openai":
                client = AsyncOpenAI(api_key=key, base_url=provider_details.get("base_url"), timeout=LLM_TIMEOUT_SECONDS)
            elif p_type == "anthropic":
                client = AsyncAnthropic(api_key=key, timeout=LLM_TIMEOUT_SECONDS)
            elif p_type == "gemini":
                client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=LLM_TIMEOUT_SECONDS * 1000))
            else:
                return None
        except Exception as e:
            self.log.error(f"Stored-key client init failed for '{provider_name}': {e}")
            return None
        self._org_clients[cache_key] = client
        return client

    def _note_truncation(self, route, provider_name, model_name, marker):
        """Record that the provider stopped because the output budget ran out.

        Every provider signals this differently and two of the three branches
        used to ignore it, so a truncated answer reached the user with nothing
        in the log and nothing in the record (GOVERNANCE_BACKLOG 85). Detection
        is per branch; what happens next is here, once.
        """
        _TRUNCATED.set(True)
        self.log.warning(
            "Generation truncated: route=%s provider=%s model=%s stopped at the "
            "output cap (%s). The answer is cut off mid-output. Raise "
            "SAFI_MAX_INTELLECT_TOKENS (currently %d) if this recurs; on a "
            "thinking model the hidden reasoning draws from the same budget.",
            route, provider_name, model_name, marker, MAX_INTELLECT_TOKENS,
        )

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
        """Dispatch one request to whichever provider the route names.

        json_mode constrains decoding to valid JSON at the API level
        (OpenAI-compatible response_format / Gemini response_mime_type). Callers
        must still instruct the model to produce JSON in the prompt —
        OpenAI-compatible providers reject json mode otherwise. Ignored when
        tools are passed (the two are incompatible) and on providers with no
        native support (Anthropic).

        Returns the assistant text, or a JSON string carrying `tool_calls` when
        the model called a tool — the agent loop parses both shapes.
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

        provider_details = self.config.get("providers", {}).get(provider_name)
        if not provider_details:
             raise ValueError(f"Provider '{provider_name}' defined in route '{route}' not found in providers config.")

        provider_type = provider_details["type"]
        # The on-box model server cannot serve a cloud-scale token budget inside
        # the per-call timeout; see LOCAL_MAX_TOKENS. Applied here rather than at
        # the call sites so no route has to know which provider it will reach.
        if provider_name == "local" and LOCAL_MAX_TOKENS > 0:
            if max_tokens > LOCAL_MAX_TOKENS:
                self.log.info(
                    "Capping %s route output at %d tokens for the local provider "
                    "(requested %d); set SAFI_LOCAL_MAX_TOKENS=0 to disable.",
                    route, LOCAL_MAX_TOKENS, max_tokens,
                )
                max_tokens = LOCAL_MAX_TOKENS
        # Cleared per call: the agent loop makes several, and only the one that
        # produced the text the user sees should be able to flag it.
        _TRUNCATED.set(False)
        # The active org's own key wins over the deployment client (backlog
        # 64) — and makes a provider usable that has no .env key at all.
        client = self._org_override_client(provider_name, provider_details) \
            or self.clients.get(provider_name)

        if not client:
            raise RuntimeError(f"Client for provider '{provider_name}' is not initialized. Check API Key.")

        # Gemini takes the history array as typed Content; every other provider
        # needs a single string, so flatten it.
        user_prompt_str = user_prompt
        if isinstance(user_prompt, list) and provider_type != "gemini":
            str_parts = []
            for item in user_prompt:
                str_parts.append(str(item))
            user_prompt_str = "\n\n".join(str_parts)

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

            if "o1" in model_name or "o3" in model_name:
                # o1 models reject the 'system' role and 'temperature', and use
                # max_completion_tokens. Tools are left as-is: the caller opted
                # in, so an API error is better than a silent drop.
                params["messages"] = [{"role": "user", "content": f"System Instruction: {system_prompt}\n\nUser Query: {user_prompt}"}]
                params.pop("temperature", None)
                params.pop("max_tokens", None)
                params["max_completion_tokens"] = max_tokens
            elif _is_openai_flagship(model_name):
                # OpenAI's first-party gpt line. The system role and
                # `response_format: json_object` both work, but `max_tokens`,
                # `top_p`, and ANY temperature other than the default all return
                # a hard 400. Verified against the live API on 2026-07-30 with
                # gpt-5.6-luna and again on 2026-09-30 with gpt-6-luna, which
                # returns the identical four rejections — so this is a property
                # of the line, not of one release.
                #
                # Gated on the "gpt-" prefix MINUS "gpt-oss", deliberately.
                # provider_type "openai" is shared with Groq, Cerebras, DeepSeek
                # and Mistral, and those must keep sending max_tokens. The
                # exclusion is what keeps Cerebras' bare "gpt-oss-*" on the old
                # parameter; Groq's "openai/gpt-oss-*" never reaches here at all.
                # Widening this to "gpt" in model_name, as the obvious fix for a
                # newly released major version looks, silently caps every
                # gpt-oss answer at the provider default — see
                # tests/test_gpt5_params.py, which pins that trap.
                #
                # A version prefix is the wrong shape for this gate, and it has
                # now broken twice: gpt-5 was unreachable because the gate still
                # read o1/o3, and gpt-6 was unreachable because the gate read
                # "gpt-5". Both times the fix was to widen the gate, not to
                # re-teach the dispatcher a new model.
                #
                # CAVEAT, deliberately not worked around: forcing the default
                # temperature costs the Conscience its temperature=0.0
                # determinism if an operator selects a gpt-5/6 model for that
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
                    # against gpt-5.6-luna and 2026-09-30 against gpt-6-luna:
                    # omitted / "low" / "medium" / "high" all 400; "minimal" is
                    # not a valid value for this model; only "none" is accepted,
                    # and it returns a proper tool_calls response.
                    #
                    # The trade-off is real: this buys tool calling by giving up
                    # the model's reasoning for that turn. Keeping tools AND
                    # reasoning requires the /v1/responses API, which is a port
                    # rather than a parameter change. Only sent when tools are
                    # present, so ordinary turns keep the model's reasoning.
                    params["reasoning_effort"] = "none"
            else:
                 params["max_tokens"] = max_tokens

            resp = await client.chat.completions.create(**params)
            self._capture_usage(route, provider_name, model_name, provider_type, resp)

            # finish_reason "length" means the response hit max_tokens. Standard
            # across OpenAI-compatible providers; zhipu reports it too, and its
            # reasoning tokens count toward the same budget.
            try:
                if resp.choices and getattr(resp.choices[0], "finish_reason", None) == "length":
                    self._note_truncation(route, provider_name, model_name, "finish_reason=length")
            except Exception:
                pass

            msg = resp.choices[0].message
            if msg.tool_calls:
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

            try:
                resp = await client.messages.create(**kwargs)
            except TypeError as exc:
                # Anthropic SDK releases have not all exposed the same keyword
                # set on AsyncMessages.create. A local signature mismatch is
                # safe to retry once without temperature; the first call fails
                # before any network request is made.
                if "unexpected keyword argument 'temperature'" not in str(exc):
                    raise
                kwargs.pop("temperature", None)
                resp = await client.messages.create(**kwargs)
            self._capture_usage(route, provider_name, model_name, provider_type, resp)

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

            # A safety refusal comes back as stop_reason "refusal" with no content
            # blocks. Surface it as a distinct, accurate error instead of letting
            # the empty content fall through to the generic "{}" / empty-response
            # path, which tells the user to check an API key that is working fine.
            # Some models (e.g. creative-writing models) refuse the Intellect's
            # reflection format on every turn, which makes them unusable here.
            if getattr(resp, "stop_reason", None) == "refusal":
                raise RuntimeError(
                    "the model refused to generate a response for this request "
                    "(stop_reason=refusal); this model may be incompatible with the "
                    "governance prompt format"
                )

            # stop_reason "max_tokens" means the budget ran out mid-answer. The
            # content blocks still hold the partial text, so without this check
            # it reaches the user mid-sentence and looks like a finished answer.
            if getattr(resp, "stop_reason", None) == "max_tokens":
                self._note_truncation(route, provider_name, model_name, "stop_reason=max_tokens")

            text_content = ""
            for block in resp.content:
                if block.type == "text":
                    text_content += block.text

            return text_content or "{}"

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
                resp = await client.aio.models.generate_content(
                    model=model_name,
                    contents=user_prompt,
                    config=config
                )
            except Exception as e:
                self.log.error(f"Gemini generation failed: {e}")
                return "{}"
            self._capture_usage(route, provider_name, model_name, provider_type, resp)

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

                        # model_dump(mode="json") is preferred when available:
                        # it keeps the payload free of Pydantic objects that
                        # json.dumps would have to stringify via safe_serialize.
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

                # Gemini stops with finish_reason=MAX_TOKENS when the output
                # (including thinking tokens) exhausts max_output_tokens;
                # resp.text still holds the partial answer. Compare on the name
                # to stay robust across SDK enum/string representations.
                try:
                    if resp.candidates:
                        finish_reason = getattr(resp.candidates[0], "finish_reason", None)
                        if finish_reason is not None and "MAX_TOKENS" in str(finish_reason):
                            self._note_truncation(
                                route, provider_name, model_name, "finish_reason=MAX_TOKENS")
                except Exception:
                    pass

                return resp.text or "{}"
            except Exception as e:
                self.log.warning(f"Gemini returned empty response or error: {e}")
                return "{}"

        else:
            raise ValueError(f"Unsupported provider type '{provider_type}'")


    # Times to re-ask the Intellect model when it returns a blank/contentless
    # response. Fast models (e.g. *-flash) intermittently emit empty content,
    # which the provider surfaces as the "{}" sentinel; each attempt resamples
    # the model so a blank never reaches the user.
    _INTELLECT_MAX_ATTEMPTS = 3

    @staticmethod
    def _is_timeout_error(exc: Exception) -> bool:
        """True if the exception is a provider stall (timeout / connection
        failure). These must NEVER be retried: a retry just runs the same hang
        again, and N attempts at the per-call timeout can add up past gunicorn's
        request timeout, which turns one stuck provider into a killed worker.
        A blank-but-fast response is a different case and is still retried."""
        text = f"{type(exc).__name__}: {exc}".lower()
        return any(k in text for k in (
            "timeout", "timed out", "connection", "connecterror",
            "readerror", "network", "unreachable", "getaddrinfo",
        ))

    @staticmethod
    def _is_refusal_error(exc: Exception) -> bool:
        """True if the model refused the request (e.g. Anthropic stop_reason
        'refusal'). Like a timeout, retrying is pointless: the same model given
        the same prompt refuses again. Fail fast rather than burn the retries."""
        return "refus" in f"{exc}".lower()

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        """True when retrying would immediately amplify provider throttling."""
        text = f"{type(exc).__name__}: {exc}".lower()
        return "429" in text or "rate limit" in text or "ratelimit" in text

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
        if "refus" in low:
            return ("the model refused to generate a response for this request. Some models, "
                    "notably creative-writing models, decline SAFi's governance and self-audit "
                    "prompt format on every turn, which makes them unusable for drafting. Choose "
                    "a general-purpose model for this agent.")
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
        """Run the configured Intellect model and parse the result.

        Returns (answer, reflection, context_for_audit, raw_turn). On a hard
        error the answer is None and `last_intellect_error` holds an
        operator-readable cause; after exhausted blank retries it is "" so the
        caller's graceful empty-response path handles it instead of surfacing
        the sentinel.
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
                    # See MAX_INTELLECT_TOKENS at the top of this module for what
                    # the budget covers and what raising it costs.
                    max_tokens=MAX_INTELLECT_TOKENS,
                    tools=tools
                )
                raw_content_stripped = raw_content.strip() if raw_content else ""

                # A tool call is a valid (non-empty) response — return immediately,
                # never retried. Extraction is by first '{'/last '}' because
                # chatty models wrap the tool-call JSON in surrounding text.
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

                if _TRUNCATED.get() and answer:
                    answer = answer.rstrip() + TRUNCATION_NOTICE

                return answer, reflection, context_for_audit, raw_turn
            except Exception as e:
                last_exc = e
                self.log.exception(
                    "Intellect execution failed (attempt %d/%d)", attempt, self._INTELLECT_MAX_ATTEMPTS
                )
                # A stalled provider must fail this turn now, not be re-run twice
                # more: three attempts at the per-call timeout would exceed the
                # request budget and kill the worker. Blanks and other transient
                # errors still retry.
                if self._is_timeout_error(e):
                    self.log.warning("Intellect call timed out; failing fast without retry.")
                    break
                if self._is_refusal_error(e):
                    self.log.warning("Intellect call was refused by the model; failing fast without retry.")
                    break
                if self._is_rate_limit_error(e):
                    self.log.warning("Intellect provider rate-limited the call; failing fast without retry.")
                    break
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
        """Run the configured Will model and parse the result.

        Never raises: any error becomes a "violation" decision, so a provider
        outage fails the turn closed rather than skipping the Will entirely.
        """
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
        """Run the configured Conscience model and parse the result.

        Model-agnostic by design. The Conscience route is whatever the operator
        configured, and this method must not know or care which model that is:
        per-model tuning here silently changes how strictly every agent in the
        deployment is audited, based on a substring match nobody reviewed. If a
        model needs a different request *shape* to be callable at all, that
        belongs in _chat_completion with the other provider adapters — it is an
        API constraint, not an audit policy.

        An empty list is the fail-closed signal: the Will then blocks, which is
        the safe outcome when the auditor is unreachable.
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
                # A stalled provider must not be re-run: a second call at the
                # per-call timeout would push the turn past the request budget.
                # Fail fast to the outer handler (empty ledger => Will fails
                # closed), which is the safe outcome when the model is unreachable.
                if self._is_timeout_error(e):
                    self.log.warning("Conscience call timed out; failing fast without retry.")
                    raise
                if self._is_rate_limit_error(e):
                    self.log.warning("Conscience provider rate-limited the call; failing fast without retry.")
                    raise
                # A provider that merely rejects json_mode would otherwise fail BOTH
                # audit attempts and brick the agent into permanent fail-closed.
                # Retry once without it; the text parser handles unconstrained output.
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
