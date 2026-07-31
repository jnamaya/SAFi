"""
The gpt-5.x OpenAI parameter contract.

WHY. OpenAI's gpt-5 family rejects three things SAFi sends by default. Probed
against the live API on 2026-07-30 with `gpt-5.6-luna`, each a hard 400:

  * `max_tokens`  -> "not supported with this model. Use 'max_completion_tokens'"
  * `temperature` -> "does not support 0.6 ... Only the default (1) value"
  * `top_p`       -> "not supported with this model"

The system role and `response_format: json_object` both work.

`llm_provider.py` only special-cased `o1`/`o3`, so the entire gpt-5 line was
unusable — including `gpt-5-mini` and `gpt-5-nano`, which are the configured
defaults for the `openai` route (`_FACULTY_DEFAULTS_BY_PROVIDER`). That means
this was a latent break, not something the new model introduced.

The trap this file guards is the *gate*, not the rewrite. `provider_type ==
"openai"` is shared with Groq, Cerebras, DeepSeek and Mistral, all of which
still need `max_tokens`. Widening the condition — to `"gpt" in model_name`, say
— silently strips `max_tokens` from Groq's `openai/gpt-oss-*` and Cerebras'
`gpt-oss-*` and caps every answer at the provider default instead. That fails
nowhere near this code, so it needs pinning here.

Captures the kwargs actually handed to the client rather than parsing source, so
it tests the dispatch path the orchestrator really takes.

Requires no database and makes no network calls. Run:
    venv/bin/python tests/test_gpt5_params.py
"""
import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.services.llm_provider import LLMProvider
from safi_app.core.services.model_routing import detect_provider
from safi_app.config import Config


class _CapturingCompletions:
    """Stands in for `client.chat.completions`, recording the call kwargs."""

    def __init__(self, sink):
        self._sink = sink

    async def create(self, **kwargs):
        self._sink.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="ok", tool_calls=None))]
        )


class _FakeClient:
    def __init__(self, sink):
        self.chat = SimpleNamespace(completions=_CapturingCompletions(sink))


def _params_for(model, **call_kwargs):
    """Run one _chat_completion against a fake client and return the kwargs."""
    sink = []
    provider = LLMProvider({
        # No api_key -> _initialize_clients skips it, so nothing real is built
        # and no key is needed to run this test.
        "providers": {"openai": {"type": "openai", "api_key": ""}},
        "routes": {"probe": {"provider": "openai", "model": model}},
    })
    provider.clients["openai"] = _FakeClient(sink)
    asyncio.run(provider._chat_completion(
        route="probe", system_prompt="sys", user_prompt="usr", **call_kwargs))
    assert len(sink) == 1, f"expected exactly one client call, got {len(sink)}"
    return sink[0]


class Gpt5ParameterContract(unittest.TestCase):

    def test_01_gpt5_uses_max_completion_tokens(self):
        p = _params_for("gpt-5.6-luna", max_tokens=8192)
        self.assertEqual(p.get("max_completion_tokens"), 8192)
        self.assertNotIn("max_tokens", p,
                         "gpt-5.x rejects max_tokens outright — it must be renamed, "
                         "not sent alongside")

    def test_02_gpt5_drops_non_default_temperature(self):
        """The Conscience scores at 0.0 and other routes at 0.1/0.6. All of them
        are 400s on gpt-5.x, so the parameter has to be omitted entirely."""
        for temp in (0.0, 0.1, 0.6):
            with self.subTest(temperature=temp):
                p = _params_for("gpt-5.6-luna", temperature=temp)
                self.assertNotIn("temperature", p,
                                 f"temperature={temp} is a hard 400 on gpt-5.x")

    def test_03_gpt5_drops_top_p(self):
        p = _params_for("gpt-5.6-luna", top_p=0.9)
        self.assertNotIn("top_p", p, "top_p is unsupported on gpt-5.x")

    def test_04_gpt5_keeps_the_system_role_and_json_mode(self):
        """Unlike o1/o3, gpt-5.x DOES accept a system message, so the o1
        flatten-into-one-user-turn rewrite must not be applied to it — doing so
        would quietly change every governed prompt."""
        p = _params_for("gpt-5.6-luna", json_mode=True)
        roles = [m["role"] for m in p["messages"]]
        self.assertEqual(roles, ["system", "user"],
                         "gpt-5.x supports the system role; do not flatten it")
        self.assertEqual(p.get("response_format"), {"type": "json_object"})

    def test_05_the_whole_gpt5_family_is_covered(self):
        """gpt-5-mini and gpt-5-nano are the configured `openai` route defaults,
        so they must be fixed by the same rule, not just the newly added id."""
        for model in ("gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5.6-luna",
                      "GPT-5.6-Luna"):
            with self.subTest(model=model):
                p = _params_for(model, max_tokens=1024, temperature=0.0)
                self.assertIn("max_completion_tokens", p)
                self.assertNotIn("max_tokens", p)
                self.assertNotIn("temperature", p)


class OtherOpenAiCompatibleProvidersAreUnaffected(unittest.TestCase):
    """The gate. These providers share provider_type "openai" and still need
    max_tokens; a broadened condition would cap their output silently."""

    def test_06_groq_and_cerebras_keep_max_tokens(self):
        for model in ("openai/gpt-oss-120b",   # Groq, vendor-prefixed
                      "openai/gpt-oss-20b",
                      "gpt-oss-120b",          # Cerebras, bare
                      "zai-glm-4.7",
                      "gemma-4-31b"):
            with self.subTest(model=model):
                p = _params_for(model, max_tokens=4096, temperature=0.2)
                self.assertEqual(p.get("max_tokens"), 4096,
                                 f"{model} needs max_tokens — it is not a gpt-5 model")
                self.assertNotIn("max_completion_tokens", p)
                self.assertEqual(p.get("temperature"), 0.2,
                                 f"{model} supports temperature; do not strip it")

    def test_07_mistral_deepseek_zhipu_keep_max_tokens(self):
        for model in ("mistral-medium-latest", "deepseek-v4-pro", "glm-5.2"):
            with self.subTest(model=model):
                p = _params_for(model, max_tokens=2048, temperature=0.1)
                self.assertEqual(p.get("max_tokens"), 2048)
                self.assertEqual(p.get("temperature"), 0.1)


class RegistryWiring(unittest.TestCase):

    def test_08_luna_is_selectable(self):
        ids = [m["id"] for m in Config.AVAILABLE_MODELS]
        self.assertIn("gpt-5.6-luna", ids)

    def test_09_luna_routes_to_openai_not_the_groq_fallback(self):
        """detect_provider is prefix matching with a `groq` default, and
        PROVIDER_METADATA is keyed per provider — so a misroute would badge an
        OpenAI model with Groq's baa_capable=False / zdr="default", publishing a
        false HIPAA/ZDR claim in the org-settings UI and on /models."""
        self.assertEqual(detect_provider("gpt-5.6-luna"), "openai")

    def test_10_every_listed_model_resolves_to_a_known_provider(self):
        from safi_app.core.services.model_routing import PROVIDER_METADATA
        for m in Config.AVAILABLE_MODELS:
            with self.subTest(model=m["id"]):
                self.assertIn(detect_provider(m["id"]), PROVIDER_METADATA,
                              f"{m['id']} resolves to a provider with no governance "
                              f"metadata, so it would render an empty badge")

    def test_11_gpt5_ids_keep_the_prefix_the_dispatcher_switches_on(self):
        """A label may say anything; the id may not. If someone "tidies" an id to
        `gpt5.6-luna`, detect_provider falls back to groq AND the parameter fix
        stops applying — two silent failures from one edit."""
        for m in Config.AVAILABLE_MODELS:
            if "5.6" in m["id"] or "gpt-5" in m["id"]:
                with self.subTest(model=m["id"]):
                    self.assertTrue(m["id"].startswith("gpt-5"),
                                    f"{m['id']} must start with 'gpt-5' exactly")


if __name__ == "__main__":
    unittest.main(verbosity=2)
