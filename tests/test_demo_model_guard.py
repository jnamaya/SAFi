import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from safi_app.core.services.model_routing import model_provider_configured


class _OpenAIOnlyInstall:
    OPENAI_API_KEY = "sk-test"


class _NoKeysInstall:
    pass


class ModelProviderConfigured(unittest.TestCase):

    def test_the_reported_bug_is_dead(self):
        self.assertFalse(model_provider_configured("gemma-4-31b", _OpenAIOnlyInstall))

    def test_a_servable_model_passes(self):
        self.assertTrue(model_provider_configured("gpt-5-mini", _OpenAIOnlyInstall))

    def test_no_keys_means_nothing_passes(self):
        self.assertFalse(model_provider_configured("gpt-5-mini", _NoKeysInstall))
        self.assertFalse(model_provider_configured("gemma-4-31b", _NoKeysInstall))


class ShippedDefaults(unittest.TestCase):

    def test_config_default_is_inherit(self):
        src = (ROOT / "safi_app" / "config.py").read_text()
        m = re.search(r'DEMO_INTELLECT_MODEL\s*=\s*os\.environ\.get\(\s*"SAFI_DEMO_INTELLECT_MODEL",\s*"(.*?)"\s*\)', src)
        self.assertIsNotNone(m, "DEMO_INTELLECT_MODEL assignment not found in config.py")
        self.assertEqual(m.group(1), "", "the shipped default must be empty (inherit global)")

    def test_env_example_ships_the_line_blank(self):
        example = (ROOT / ".env.example").read_text()
        m = re.search(r"^SAFI_DEMO_INTELLECT_MODEL=(.*)$", example, re.M)
        self.assertIsNotNone(m, "SAFI_DEMO_INTELLECT_MODEL missing from .env.example")
        self.assertEqual(m.group(1).strip(), "",
                         ".env.example must not ship a provider-specific demo model")

    def test_guest_creation_uses_the_guard(self):
        src = (ROOT / "safi_app" / "api" / "auth.py").read_text()
        self.assertIn("model_provider_configured(Config.DEMO_INTELLECT_MODEL", src,
                      "guest creation no longer guards the demo model write")


if __name__ == "__main__":
    unittest.main()
