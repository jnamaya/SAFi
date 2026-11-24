import asyncio
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.core.services.llm_provider import LLMProvider
from safi_app.core.services.model_routing import detect_provider
from safi_app.config import Config


class _CapturingCompletions:

    def __init__(self, sink):
        self._sink = sink

    def create(self, **kwargs):
        self._sink.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="ok", tool_calls=None))]
        )


class _FakeClient:
    def __init__(self, sink):
        self.chat = SimpleNamespace(completions=_CapturingCompletions(sink))


def _params_for(model, **call_kwargs):
    sink = []
    provider = LLMProvider({
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
        for temp in (0.0, 0.1, 0.6):
            with self.subTest(temperature=temp):
                p = _params_for("gpt-5.6-luna", temperature=temp)
                self.assertNotIn("temperature", p,
                                 f"temperature={temp} is a hard 400 on gpt-5.x")

    def test_03_gpt5_drops_top_p(self):
        p = _params_for("gpt-5.6-luna", top_p=0.9)
        self.assertNotIn("top_p", p, "top_p is unsupported on gpt-5.x")

    def test_04_gpt5_keeps_the_system_role_and_json_mode(self):
        p = _params_for("gpt-5.6-luna", json_mode=True)
        roles = [m["role"] for m in p["messages"]]
        self.assertEqual(roles, ["system", "user"],
                         "gpt-5.x supports the system role; do not flatten it")
        self.assertEqual(p.get("response_format"), {"type": "json_object"})

    def test_05_the_whole_gpt5_family_is_covered(self):
        for model in ("gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5.6-luna",
                      "GPT-5.6-Luna"):
            with self.subTest(model=model):
                p = _params_for(model, max_tokens=1024, temperature=0.0)
                self.assertIn("max_completion_tokens", p)
                self.assertNotIn("max_tokens", p)
                self.assertNotIn("temperature", p)


class Gpt6SharesTheGpt5Contract(unittest.TestCase):

    def test_16_gpt6_reaches_the_gpt5_branch(self):
        for model in ("gpt-6-luna", "gpt-6-astra", "gpt-6-sol", "gpt-6.1-sol",
                      "GPT-6-Luna"):
            with self.subTest(model=model):
                p = _params_for(model, max_tokens=1024, temperature=0.1, top_p=0.9)
                self.assertEqual(p.get("max_completion_tokens"), 1024)
                self.assertNotIn("max_tokens", p)
                self.assertNotIn("temperature", p)
                self.assertNotIn("top_p", p)

    def test_17_gpt6_keeps_the_system_role(self):
        p = _params_for("gpt-6-luna", max_tokens=1024)
        self.assertEqual([m["role"] for m in p["messages"]], ["system", "user"])

    def test_18_gpt6_tools_disable_reasoning(self):
        p = _params_for("gpt-6-luna", max_tokens=1024, tools=_TOOLS)
        self.assertEqual(p.get("reasoning_effort"), "none")
        self.assertTrue(p.get("tools"))

    def test_19_a_new_major_version_needs_no_edit(self):
        from safi_app.core.services.llm_provider import _is_openai_flagship
        for major in range(5, 12):
            for suffix in ("", "-luna", "-mini", "-pro"):
                model = f"gpt-{major}{suffix}"
                with self.subTest(model=model):
                    self.assertTrue(_is_openai_flagship(model),
                                    f"{model} is OpenAI's own line and must be "
                                    f"covered without a code change")

    def test_20_gpt_oss_stays_excluded_at_every_version(self):
        from safi_app.core.services.llm_provider import _is_openai_flagship
        for model in ("gpt-oss-20b", "gpt-oss-120b", "openai/gpt-oss-20b",
                      "openai/gpt-oss-120b", "gpt-oss-6-luna"):
            with self.subTest(model=model):
                self.assertFalse(_is_openai_flagship(model),
                                 f"{model} is gpt-oss, not the flagship line")
        for model in ("gpt-oss-120b", "openai/gpt-oss-120b"):
            with self.subTest(model=model):
                p = _params_for(model, max_tokens=4096, temperature=0.2)
                self.assertEqual(p.get("max_tokens"), 4096)
                self.assertNotIn("max_completion_tokens", p)
                self.assertEqual(p.get("temperature"), 0.2)


_TOOLS = [{
    "name": "get_quote",
    "description": "Get a stock quote",
    "input_schema": {"type": "object",
                     "properties": {"ticker": {"type": "string"}},
                     "required": ["ticker"]},
}]


class Gpt5ToolCalling(unittest.TestCase):

    def test_12_tools_on_gpt5_disable_reasoning(self):
        p = _params_for("gpt-5.6-luna", max_tokens=8192, tools=_TOOLS)
        self.assertEqual(p.get("reasoning_effort"), "none",
                         'gpt-5.x rejects function tools unless reasoning_effort is '
                         '"none" — this is what made a tool-enabled agent fail on '
                         'every turn')
        self.assertTrue(p.get("tools"), "the tools must still be sent")

    def test_13_reasoning_is_untouched_when_there_are_no_tools(self):
        p = _params_for("gpt-5.6-luna", max_tokens=8192)
        self.assertNotIn("reasoning_effort", p,
                         "a turn with no tools must keep the model's default "
                         "reasoning")

    def test_14_only_none_is_used(self):
        p = _params_for("gpt-5.6-luna", max_tokens=8192, tools=_TOOLS)
        self.assertNotIn(p.get("reasoning_effort"),
                         ("minimal", "low", "medium", "high"))

    def test_15_other_providers_get_no_reasoning_effort(self):
        for model in ("openai/gpt-oss-120b", "gpt-oss-120b", "mistral-small-2603",
                      "mistral-medium-latest"):
            with self.subTest(model=model):
                p = _params_for(model, max_tokens=4096, tools=_TOOLS)
                self.assertNotIn("reasoning_effort", p,
                                 f"{model} does not accept reasoning_effort")
                self.assertTrue(p.get("tools"))


class OtherOpenAiCompatibleProvidersAreUnaffected(unittest.TestCase):

    def test_06_groq_and_cerebras_keep_max_tokens(self):
        for model in ("openai/gpt-oss-120b",
                      "openai/gpt-oss-20b",
                      "gpt-oss-120b",
                      "qwen-3.8-27b"):
            with self.subTest(model=model):
                p = _params_for(model, max_tokens=4096, temperature=0.2)
                self.assertEqual(p.get("max_tokens"), 4096,
                                 f"{model} needs max_tokens — it is not a gpt-5 model")
                self.assertNotIn("max_completion_tokens", p)
                self.assertEqual(p.get("temperature"), 0.2,
                                 f"{model} supports temperature; do not strip it")

    def test_07_mistral_deepseek_zhipu_keep_max_tokens(self):
        for model in ("mistral-small-2603", "mistral-medium-latest",
                      "deepseek-v4-pro", "glm-5.2"):
            with self.subTest(model=model):
                p = _params_for(model, max_tokens=2048, temperature=0.1)
                self.assertEqual(p.get("max_tokens"), 2048)
                self.assertEqual(p.get("temperature"), 0.1)

    def test_07b_zhipu_glm_disables_thinking_when_tools_present(self):
        tools = [{"name": "read", "description": "Read file", "input_schema": {"type": "object"}}]
        p_tools = _params_for("glm-5.3", max_tokens=2048, temperature=0.1, tools=tools)
        self.assertEqual(p_tools.get("max_tokens"), 2048)
        self.assertEqual(p_tools.get("extra_body"), {"thinking": {"type": "disabled"}})

        p_prose = _params_for("glm-5.3", max_tokens=2048, temperature=0.1)
        self.assertIsNone(p_prose.get("extra_body"))


class RegistryWiring(unittest.TestCase):

    def test_08_luna_is_selectable(self):
        ids = [m["id"] for m in Config.AVAILABLE_MODELS]
        self.assertIn("gpt-6-luna", ids)

    def test_09_luna_routes_to_openai_not_the_groq_fallback(self):
        self.assertEqual(detect_provider("gpt-6-luna"), "openai")

    def test_09b_qwen_routes_to_cerebras_not_the_groq_fallback(self):
        self.assertEqual(detect_provider("qwen-3.8-27b"), "cerebras")
        for model in ("qwen-3.8-27b", "qwen-4-405b", "qwen-3.8-235b-a22b"):
            with self.subTest(model=model):
                self.assertEqual(detect_provider(model), "cerebras")

    def test_10_every_listed_model_resolves_to_a_known_provider(self):
        from safi_app.core.services.model_routing import PROVIDER_METADATA
        for m in Config.AVAILABLE_MODELS:
            with self.subTest(model=m["id"]):
                self.assertIn(detect_provider(m["id"]), PROVIDER_METADATA,
                              f"{m['id']} resolves to a provider with no governance "
                              f"metadata, so it would render an empty badge")

    def test_11_gpt_ids_keep_the_prefix_the_dispatcher_switches_on(self):
        for m in Config.AVAILABLE_MODELS:
            if re.match(r"^gpt-\d", m["id"]):
                with self.subTest(model=m["id"]):
                    self.assertTrue(m["id"].startswith("gpt-"),
                                    f"{m['id']} must start with 'gpt-' exactly")


if __name__ == "__main__":
    unittest.main(verbosity=2)
