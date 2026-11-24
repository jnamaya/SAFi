from __future__ import annotations
import os
import json
import logging
import asyncio
from typing import List, Dict, Any, Tuple, Optional
from contextvars import ContextVar

from openai import OpenAI
from anthropic import Anthropic
from google import genai
from google.genai import types
import httpx

from .parsing_utils import (
    parse_intellect_response,
    parse_will_response,
    parse_conscience_response,
    parse_tool_calls_from_text,
    robust_json_parse,
    salvage_tool_call_arguments,
)

from ..faculties.conscience import CONSCIENCE_TEMPERATURE


LLM_TIMEOUT_SECONDS = int(os.environ.get("SAFI_LLM_TIMEOUT", "300"))
CONSCIENCE_TIMEOUT_SECONDS = float(os.environ.get("SAFI_CONSCIENCE_TIMEOUT", "45"))


MAX_INTELLECT_TOKENS = int(os.environ.get("SAFI_MAX_INTELLECT_TOKENS", "65536"))


LOCAL_MAX_TOKENS = int(os.environ.get("SAFI_LOCAL_MAX_TOKENS", "1024"))


LOCAL_INTELLECT_MAX_TOKENS = int(
    os.environ.get("SAFI_LOCAL_INTELLECT_MAX_TOKENS", str(MAX_INTELLECT_TOKENS))
)


class ProviderRequestError(RuntimeError):

    def __init__(self, provider: str, endpoint: str, status_code=None, detail=""):
        self.provider = str(provider or "unknown")
        self.endpoint = str(endpoint or "")
        self.status_code = status_code
        self.detail = str(detail or "")[:500]
        status = f" HTTP {status_code}" if status_code is not None else ""
        message = f"{self.provider}{status} rejected request to {self.endpoint or 'provider endpoint'}"
        if self.detail:
            message += f": {self.detail}"
        super().__init__(message)


_TRUNCATED: ContextVar[bool] = ContextVar("safi_generation_truncated", default=False)

_REASONING_EFFORT: ContextVar[str] = ContextVar("safi_reasoning_effort", default="")


def set_reasoning_effort(level: str) -> None:
    _REASONING_EFFORT.set((level or "").strip().lower())


def current_reasoning_effort() -> str:
    return _REASONING_EFFORT.get()


TRUNCATION_NOTICE = (
    "\n\n(This answer is incomplete. It reached the output limit for a single "
    "turn and stopped here. Ask to continue and it will pick up from this point.)"
)


def generation_was_truncated() -> bool:
    return _TRUNCATED.get()


def _is_openai_flagship(model_name: str) -> bool:
    m = (model_name or "").lower()
    return m.startswith("gpt-") and not m.startswith("gpt-oss")


def _provider_error_detail(response) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error", payload)
        if isinstance(error, dict):
            for key in ("message", "detail", "code", "type"):
                value = error.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()[:500]
        elif isinstance(error, str):
            return error.strip()[:500]
    text = getattr(response, "text", "")
    return text.strip()[:500] if isinstance(text, str) else ""


class LLMProvider:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.log = logging.getLogger(self.__class__.__name__)
        self.clients = {}
        self._org_clients: Dict[Any, Any] = {}
        self._route_override_clients: Dict[Any, Any] = {}
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
                    self.clients[name] = OpenAI(
                        api_key=api_key,
                        base_url=details.get("base_url"),
                        timeout=LLM_TIMEOUT_SECONDS,
                    )
                elif p_type == "anthropic":
                    self.clients[name] = Anthropic(api_key=api_key, timeout=LLM_TIMEOUT_SECONDS)
                elif p_type == "gemini":
                    self.clients[name] = genai.Client(
                        api_key=api_key,
                        http_options=types.HttpOptions(timeout=LLM_TIMEOUT_SECONDS * 1000),
                    )
                else:
                    self.log.error(f"Unknown provider type '{p_type}' for '{name}'")
            except Exception as e:
                self.log.error(f"Failed to initialize provider '{name}': {e}")
        self._init_route_override_clients(providers)

    def _init_route_override_clients(self, providers: Dict[str, Any]) -> None:
        for route_name, route in (self.config.get("routes") or {}).items():
            if not isinstance(route, dict):
                continue
            override = (route.get("base_url") or "").strip()
            if not override:
                continue
            provider_name = route.get("provider")
            details = providers.get(provider_name) or {}
            if (details.get("type") != "openai"
                    or (details.get("base_url") or "").strip() == override
                    or not details.get("api_key")):
                continue
            try:
                self._route_override_clients[(route_name, provider_name)] = OpenAI(
                    api_key=details["api_key"],
                    base_url=override,
                    timeout=LLM_TIMEOUT_SECONDS,
                )
            except Exception as e:
                self.log.error(
                    f"Failed to initialize base_url override for route '{route_name}': {e}"
                )

    def uses_typed_conscience(self) -> bool:
        return False

    def tool_call_history_entry(self, tool_name: str, arguments: str,
                                raw_turn: Optional[Dict[str, Any]] = None):
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
        route = self.config.get("routes", {}).get("intellect", {})
        provider = route.get("provider")
        details = self.config.get("providers", {}).get(provider, {})
        if details.get("type") == "gemini":
            from google.genai import types
            part = types.Part.from_function_response(name=tool_name, response={"result": result})
            return types.Content(role="user", parts=[part])
        return f"TOOL RESULT for {tool_name}:\n{result}"

    def _org_override_client(self, provider_name: str, provider_details: Dict[str, Any]):
        from .deployment_keys import resolve_provider_key
        env_key = (provider_details or {}).get("api_key")
        key = resolve_provider_key(provider_name, env_key)
        if not key or key == env_key:
            return None
        cache_key = (provider_name, key)
        client = self._org_clients.get(cache_key)
        if client is not None:
            return client
        try:
            p_type = provider_details.get("type")
            if p_type == "openai":
                client = OpenAI(api_key=key, base_url=provider_details.get("base_url"), timeout=LLM_TIMEOUT_SECONDS)
            elif p_type == "anthropic":
                client = Anthropic(api_key=key, timeout=LLM_TIMEOUT_SECONDS)
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
        _TRUNCATED.set(True)
        self.log.warning(
            "Generation truncated: route=%s provider=%s model=%s stopped at the "
            "output cap (%s). The answer is cut off mid-output. Raise "
            "SAFI_MAX_INTELLECT_TOKENS (currently %d) if this recurs; on a "
            "thinking model the hidden reasoning draws from the same budget.",
            route, provider_name, model_name, marker, MAX_INTELLECT_TOKENS,
        )

    def _capture_usage(self, route, provider_name, model_name, provider_type, resp):
        from .usage_tracking import capture_call_usage, extract_usage, record_usage
        usage = extract_usage(provider_type, resp)
        if usage:
            capture_call_usage(route, provider_name, model_name, usage[0], usage[1])
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
        route_config = self.config.get("routes", {}).get(route)
        if not route_config:
            raise ValueError(f"No route configuration found for '{route}'")

        provider_name = route_config["provider"]
        model_name = route_config["model"]

        from .provider_governance import assert_provider_allowed
        assert_provider_allowed(provider_name, context=f"route:{route}, model:{model_name}")

        provider_details = self.config.get("providers", {}).get(provider_name)
        if not provider_details:
             raise ValueError(f"Provider '{provider_name}' defined in route '{route}' not found in providers config.")

        provider_type = provider_details["type"]
        if provider_name == "local":
            ceiling = LOCAL_INTELLECT_MAX_TOKENS if route == "intellect" else LOCAL_MAX_TOKENS
            if ceiling > 0 and max_tokens > ceiling:
                self.log.info(
                    "Capping %s route output at %d tokens for the local provider "
                    "(requested %d); set SAFI_LOCAL_INTELLECT_MAX_TOKENS=0 (Intellect) "
                    "or SAFI_LOCAL_MAX_TOKENS=0 (other routes) to disable.",
                    route, ceiling, max_tokens,
                )
                max_tokens = ceiling

            if route == "intellect" and (model_name.startswith("safi-") or model_name in ("local", "@local", "serving", "@serving")):
                if model_name in ("local", "@local", "serving", "@serving"):
                    from ...config import active_local_model
                    model_name = active_local_model() or model_name
                try:
                    from .provider_governance import ensure_local_model
                    ready = await ensure_local_model(model_name)
                    if not ready:
                        self.log.warning(
                            "ensure_local_model timed out or failed to activate %s on 8081",
                            model_name,
                        )
                except Exception as exc:
                    self.log.error("Failed during on-demand model activation for %s: %s", model_name, exc)
        _TRUNCATED.set(False)
        route_override = getattr(self, "_route_override_clients", {}).get((route, provider_name))
        client = route_override \
            or self._org_override_client(provider_name, provider_details) \
            or self.clients.get(provider_name)

        if not client:
            raise RuntimeError(f"Client for provider '{provider_name}' is not initialized. Check API Key.")

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
                params["messages"] = [{"role": "user", "content": f"System Instruction: {system_prompt}\n\nUser Query: {user_prompt}"}]
                params.pop("temperature", None)
                params.pop("max_tokens", None)
                params["max_completion_tokens"] = max_tokens
            elif _is_openai_flagship(model_name):
                params.pop("temperature", None)
                params.pop("top_p", None)
                params["max_completion_tokens"] = max_tokens
                if params.get("tools"):
                    params["reasoning_effort"] = "none"
            elif route == "intellect" and _REASONING_EFFORT.get():
                params["reasoning_effort"] = _REASONING_EFFORT.get()
            else:
                 params["max_tokens"] = max_tokens
                 if (
                     params.get("tools")
                     and (provider_name == "zhipu" or model_name.lower().startswith("glm-"))
                     and os.environ.get("SAFI_ZHIPU_TOOL_THINKING", "0").strip().lower() not in ("1", "true", "yes", "on")
                 ):
                     eb = dict(params.get("extra_body") or {})
                     if "thinking" not in eb:
                         eb["thinking"] = {"type": "disabled"}
                     params["extra_body"] = eb

            if provider_name == "local":
                if "gemma" in model_name.lower():
                    existing_stops = list(params.get("stop") or [])
                    for st in ("<end_of_turn>", "<start_of_turn>", "<|turn>", "<turn|>"):
                        if st not in existing_stops:
                            existing_stops.append(st)
                    params["stop"] = existing_stops

                if route == "intellect" and _REASONING_EFFORT.get():
                    local_effort = _REASONING_EFFORT.get()
                    eb = dict(params.get("extra_body") or {})
                    ctk = dict(eb.get("chat_template_kwargs") or {})
                    ctk["enable_thinking"] = local_effort in ("low", "medium", "high")
                    eb["chat_template_kwargs"] = ctk
                    params["extra_body"] = eb
                elif route == "conscience":
                    eb = dict(params.get("extra_body") or {})
                    ctk = dict(eb.get("chat_template_kwargs") or {})
                    ctk["enable_thinking"] = False
                    eb["chat_template_kwargs"] = ctk
                    params["extra_body"] = eb

            resp = await asyncio.to_thread(client.chat.completions.create, **params)
            self._capture_usage(route, provider_name, model_name, provider_type, resp)

            try:
                if resp.choices and getattr(resp.choices[0], "finish_reason", None) == "length":
                    self._note_truncation(route, provider_name, model_name, "finish_reason=length")
            except Exception:
                pass

            msg = resp.choices[0].message
            if msg.tool_calls:
                finish_reason = getattr(resp.choices[0], "finish_reason", None)
                calls = []
                for tc in msg.tool_calls:
                    raw_args_str = tc.function.arguments or ""
                    arguments = robust_json_parse(raw_args_str, self.log)
                    if "error" in arguments:
                        salvaged = salvage_tool_call_arguments(tc.function.name, raw_args_str, self.log)
                        if salvaged is not None:
                            self.log.info(
                                "LLMProvider: salvaged malformed arguments for tool '%s': %s",
                                tc.function.name,
                                repr(raw_args_str[:120])
                            )
                            arguments = salvaged
                        else:
                            raise RuntimeError(
                                f"the model's tool call arguments for '{tc.function.name}' were not valid JSON "
                                f"({arguments.get('error')}); "
                                + ("the generation was truncated at the output-token cap "
                                   "before the arguments closed"
                                   if finish_reason == "length"
                                   else "the model emitted malformed tool-call JSON")
                            )
                    calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": arguments,
                    })
                return json.dumps({"tool_calls": calls})

            content_text = msg.content or ""
            if "<tool_call" in content_text:
                salvaged = parse_tool_calls_from_text(content_text, self.log)
                if salvaged:
                    return json.dumps({"tool_calls": salvaged})

            return content_text or "{}"

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

            effort_override = _REASONING_EFFORT.get() if route == "intellect" else None
            thinking_env = effort_override or os.environ.get("SAFI_ANTHROPIC_THINKING", "disabled").lower()
            if route == "conscience":
                thinking_env = "disabled"
            if thinking_env == "disabled":
                if "sonnet" in model_name:
                    kwargs["thinking"] = {"type": "between_tools"}
                elif "opus" in model_name:
                    kwargs["thinking"] = {"type": "adaptive"}
                    kwargs["output_config"] = {"effort": "low"}
                else:
                    kwargs["thinking"] = {"type": "disabled"}
            elif thinking_env in ("low", "medium", "high"):
                kwargs["thinking"] = {"type": "adaptive"}
                kwargs["output_config"] = {"effort": thinking_env}

            try:
                resp = await asyncio.to_thread(client.messages.create, **kwargs)
            except Exception as exc:
                if "thinking" in str(exc).lower() and "thinking" in kwargs:
                    kwargs.pop("thinking", None)
                    kwargs.pop("output_config", None)
                    try:
                        resp = await asyncio.to_thread(client.messages.create, **kwargs)
                    except TypeError as t_exc:
                        if "unexpected keyword argument 'temperature'" not in str(t_exc):
                            raise
                        kwargs.pop("temperature", None)
                        resp = await asyncio.to_thread(client.messages.create, **kwargs)
                elif isinstance(exc, TypeError) and "unexpected keyword argument 'temperature'" in str(exc):
                    kwargs.pop("temperature", None)
                    resp = await asyncio.to_thread(client.messages.create, **kwargs)
                else:
                    raise
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

            if getattr(resp, "stop_reason", None) == "refusal":
                raise RuntimeError(
                    "the model refused to generate a response for this request "
                    "(stop_reason=refusal); this model may be incompatible with the "
                    "governance prompt format"
                )

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

            config_kwargs = dict(
                system_instruction=system_prompt,
                temperature=temperature,
                max_output_tokens=max_tokens,
                tools=gemini_tools,
                response_mime_type="application/json" if (json_mode and not gemini_tools) else None,
            )

            gemini_effort = _REASONING_EFFORT.get() if route == "intellect" else None
            if route == "conscience":
                config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
            elif gemini_effort == "off":
                config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
            elif gemini_effort in ("low", "medium", "high"):
                budget = {"low": 1024, "medium": 8192, "high": -1}[gemini_effort]
                config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=budget)

            config = types.GenerateContentConfig(**config_kwargs)

            try:
                resp = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model_name,
                    contents=user_prompt,
                    config=config,
                )
            except Exception as e:
                self.log.error(f"Gemini generation failed: {e}")
                raise
            self._capture_usage(route, provider_name, model_name, provider_type, resp)

            try:
                if getattr(resp, 'function_calls', None):
                    fc = resp.function_calls[0]
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


    _INTELLECT_MAX_ATTEMPTS = 3

    @staticmethod
    def _is_timeout_error(exc: Exception) -> bool:
        text = f"{type(exc).__name__}: {exc}".lower()
        return any(k in text for k in (
            "timeout", "timed out", "connection", "connecterror",
            "readerror", "network", "unreachable", "getaddrinfo",
        ))

    @staticmethod
    def _is_refusal_error(exc: Exception) -> bool:
        return "refus" in f"{exc}".lower()

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        text = f"{type(exc).__name__}: {exc}".lower()
        return any(k in text for k in ("429", "rate limit", "ratelimit", "resource_exhausted", "quota"))

    @staticmethod
    def _is_truncation_error(exc: Exception) -> bool:
        text = f"{type(exc).__name__}: {exc}".lower()
        return "truncated at the output-token cap" in text or ("truncated" in text and "token cap" in text)

    @staticmethod
    def explain_provider_error(exc: Exception) -> str:
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
        if "truncated at the output-token cap" in low:
            return ("the model returned a tool call whose arguments were truncated at the "
                    "output-token cap before closing. Raise SAFI_LOCAL_INTELLECT_MAX_TOKENS "
                    "(or SAFI_LOCAL_MAX_TOKENS on older configs) / SAFI_MAX_INTELLECT_TOKENS "
                    "and retry.")
        if "tool call" in low or "tool-call" in low:
            return ("the model returned a tool call with malformed arguments that could not "
                    "be parsed or salvaged. Try rephrasing your request to clarify the expected action or format.")
        return f"the model provider call failed — {text[:200]}"

    @staticmethod
    def _is_contentless_intellect_answer(answer: Optional[str]) -> bool:
        if not answer or not answer.strip():
            return True
        return answer.strip() in ("{}", "[]")

    async def run_intellect(self, system_prompt: str, user_prompt: Any, context_for_audit: str, tools: Optional[List[Dict[str, Any]]] = None) -> Tuple[str, str, str, Optional[Dict[str, Any]]]:
        last_exc: Optional[Exception] = None
        self.last_intellect_error: Optional[str] = None
        for attempt in range(1, self._INTELLECT_MAX_ATTEMPTS + 1):
            try:
                raw_content = await self._chat_completion(
                    route="intellect",
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=1.0,
                    max_tokens=MAX_INTELLECT_TOKENS,
                    tools=tools
                )
                raw_content_stripped = raw_content.strip() if raw_content else ""

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

                if "<tool_call" in raw_content_stripped:
                    salvaged = parse_tool_calls_from_text(raw_content_stripped, self.log)
                    if salvaged:
                        return json.dumps({"tool_calls": salvaged}), "Tool Call", context_for_audit, None

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
                if self._is_timeout_error(e):
                    self.log.warning("Intellect call timed out; failing fast without retry.")
                    break
                if self._is_refusal_error(e):
                    self.log.warning("Intellect call was refused by the model; failing fast without retry.")
                    break
                if self._is_rate_limit_error(e):
                    self.log.warning("Intellect provider rate-limited the call; failing fast without retry.")
                    break
                if self._is_truncation_error(e):
                    self.log.warning("Intellect generation exceeded output token cap; failing fast without retry.")
                    break
                continue

        if last_exc is not None:
            self.last_intellect_error = self.explain_provider_error(last_exc)
            return None, None, context_for_audit, None
        self.log.error("Intellect returned blank after %d attempts.", self._INTELLECT_MAX_ATTEMPTS)
        return "", "", context_for_audit, None

    async def run_will(self, system_prompt: str, user_prompt: str) -> Tuple[str, str]:
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
        try:
            ledger: List[Dict[str, Any]] = []
            try:
                raw_content = await asyncio.wait_for(
                    self._chat_completion(
                        route="conscience",
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        temperature=CONSCIENCE_TEMPERATURE,
                        max_tokens=8192,
                        json_mode=True,
                    ),
                    timeout=CONSCIENCE_TIMEOUT_SECONDS,
                )
                ledger = parse_conscience_response(raw_content, self.log)
                if ledger:
                    return ledger
                self.log.warning("Conscience json_mode returned an empty/unusable ledger; retrying without json_mode.")
            except asyncio.TimeoutError:
                self.log.warning(
                    "Conscience json_mode call timed out after %.1fs; retrying without json_mode.",
                    CONSCIENCE_TIMEOUT_SECONDS,
                )
            except Exception as e:
                if self._is_timeout_error(e):
                    self.log.warning("Conscience call timed out; failing fast without retry.")
                    raise
                if self._is_rate_limit_error(e):
                    self.log.warning("Conscience provider rate-limited the call; failing fast without retry.")
                    raise
                self.log.warning(f"Conscience json_mode call failed ({e}); retrying without json_mode.")

            raw_content = await asyncio.wait_for(
                self._chat_completion(
                    route="conscience",
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=CONSCIENCE_TEMPERATURE,
                    max_tokens=8192,
                ),
                timeout=CONSCIENCE_TIMEOUT_SECONDS,
            )
            return parse_conscience_response(raw_content, self.log)
        except Exception as e:
            self.log.exception("Conscience execution failed")
            return []
