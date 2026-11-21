"""Tests for configurable TTS availability (Config.tts_enabled)."""
from unittest.mock import patch

from safi_app.config import Config


def test_tts_disabled_when_explicitly_turned_off():
    with patch.object(Config, "TTS_ENABLED_ENV", "false"), \
         patch.object(Config, "TTS_MODEL", "edge-tts"):
        assert Config.tts_enabled() is False


def test_tts_disabled_when_model_empty_or_none():
    for val in ("", "none", "off", "disabled", "false"):
        with patch.object(Config, "TTS_ENABLED_ENV", ""), \
             patch.object(Config, "TTS_MODEL", val):
            assert Config.tts_enabled() is False


def test_tts_voxtral_requires_mistral_key():
    with patch.object(Config, "TTS_ENABLED_ENV", ""), \
         patch.object(Config, "TTS_MODEL", "voxtral-mini-tts-2603"), \
         patch.object(Config, "MISTRAL_API_KEY", None):
        assert Config.tts_enabled() is False

    with patch.object(Config, "TTS_ENABLED_ENV", ""), \
         patch.object(Config, "TTS_MODEL", "voxtral-mini-tts-2603"), \
         patch.object(Config, "MISTRAL_API_KEY", "test-key"):
        assert Config.tts_enabled() is True


def test_tts_edge_tts_enabled_without_api_key():
    with patch.object(Config, "TTS_ENABLED_ENV", ""), \
         patch.object(Config, "TTS_MODEL", "edge-tts"):
        assert Config.tts_enabled() is True
