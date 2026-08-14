"""
Guests must never be handed a model this install cannot serve.

WHY. The install wizard configures one provider key, but guest login used to
store a hardcoded demo model ("gemma-4-31b", which routes to Cerebras) as the
guest's personal selection. On every non-Cerebras install that gave guests a
hyphen in the model menu and "Client for provider 'cerebras' is not
initialized" on their first prompt, while the admin account worked fine
because it inherits the key-following global default. Found by Nelson while
testing the v1.4 release.

Three things pinned here:

1. `model_provider_configured` says whether a model's provider has a key.
2. The shipped default for SAFI_DEMO_INTELLECT_MODEL is empty (inherit the
   global default), checked in the source so the test env cannot mask it.
3. `.env.example` ships the variable blank, because the example file is what
   every install actually copies; a bad value there outlives any code fix.

No database needed; this file runs standalone.

Run:  venv/bin/python tests/test_demo_model_guard.py
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from safi_app.core.services.model_routing import model_provider_configured


class _OpenAIOnlyInstall:
    """A config as the wizard leaves it: exactly one provider key set."""
    OPENAI_API_KEY = "sk-test"


class _NoKeysInstall:
    pass


class ModelProviderConfigured(unittest.TestCase):

    def test_the_reported_bug_is_dead(self):
        """gemma-4-31b routes to cerebras; an OpenAI-only install must refuse
        to store it for a guest."""
        self.assertFalse(model_provider_configured("gemma-4-31b", _OpenAIOnlyInstall))

    def test_a_servable_model_passes(self):
        self.assertTrue(model_provider_configured("gpt-5-mini", _OpenAIOnlyInstall))

    def test_no_keys_means_nothing_passes(self):
        self.assertFalse(model_provider_configured("gpt-5-mini", _NoKeysInstall))
        self.assertFalse(model_provider_configured("gemma-4-31b", _NoKeysInstall))


class ShippedDefaults(unittest.TestCase):

    def test_config_default_is_inherit(self):
        """Read the source, not Config: the test environment may set the var,
        and what we are pinning is what fresh installs get."""
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
        """auth.py must consult model_provider_configured before storing the
        demo model on a guest account."""
        src = (ROOT / "safi_app" / "api" / "auth.py").read_text()
        self.assertIn("model_provider_configured(Config.DEMO_INTELLECT_MODEL", src,
                      "guest creation no longer guards the demo model write")


if __name__ == "__main__":
    unittest.main()
