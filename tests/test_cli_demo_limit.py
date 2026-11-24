from unittest.mock import patch

from flask import Flask

from safi_app.api.conversations import conversations_bp
from safi_app.config import Config


def _make_app():
    app = Flask(__name__)
    app.register_blueprint(conversations_bp, url_prefix="/api")
    return app


def test_cli_turn_blocks_after_demo_limit_reached():
    app = _make_app()
    client = app.test_client()

    with patch.object(Config, "CLI_DEMO_TURN_LIMIT", 10), \
         patch("safi_app.api.conversations.db.get_policy_id_by_api_key", return_value="pol-1"), \
         patch("safi_app.api.conversations.db.get_todays_prompt_count", return_value=10):
        resp = client.post(
            "/api/agentic/process_prompt",
            headers={"X-API-KEY": "demo-key", "X-Forwarded-For": "203.0.113.5"},
            json={"user_id": "u1", "message": "hello", "conversation_id": "c1"},
        )

    assert resp.status_code == 429
    body = resp.get_json()
    assert body["code"] == "DEMO_LIMIT_REACHED"
    assert "10 turns/day" in body["error"]
