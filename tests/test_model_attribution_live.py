"""Tests for live llama-server model attribution resolution."""
import io
import json
from unittest.mock import patch

from safi_app.runtime_factory import _enrich_model_attribution


def test_enrich_model_attribution_prefers_live_llama_server_alias():
    live_payload = {
        "data": [
            {"id": "safi-conscience", "aliases": ["safi-conscience", "safi-gemma4-26b-a4b"]}
        ]
    }
    resp = io.BytesIO(json.dumps(live_payload).encode("utf-8"))
    resp.__enter__ = lambda s: s
    resp.__exit__ = lambda s, *a: None

    with patch("urllib.request.urlopen", return_value=resp):
        attr = _enrich_model_attribution("local", "safi-conscience", base_url="http://127.0.0.1:8082/v1")

    assert "safi-gemma4-26b-a4b" in attr
    assert "qwen" not in attr
