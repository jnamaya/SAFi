"""User model updates preserve independent faculty selections."""
from flask import Flask

from safi_app.api import auth as auth_api


def _client():
    app = Flask(__name__)
    app.secret_key = "test-session-secret"
    app.register_blueprint(auth_api.auth_bp, url_prefix="/api")
    app.testing = True
    return app.test_client()


def test_intellect_only_change_preserves_jev_conscience(monkeypatch):
    stored = {"intellect_model": "gpt-5.6-luna", "will_model": None,
              "conscience_model": "jev-1.13.0"}
    written = []
    monkeypatch.setattr(auth_api.db, "get_user_details", lambda _user: dict(stored))
    monkeypatch.setattr(auth_api.db, "update_user_models",
                        lambda _user, intellect, will, conscience:
                        written.append((intellect, will, conscience)))
    client = _client()
    with client.session_transaction() as session:
        session["user_id"] = "user-1"

    response = client.put("/api/me/models", json={"intellect_model": "gemini-3.7-flash"})

    assert response.status_code == 200
    assert written == [("gemini-3.7-flash", None, "jev-1.13.0")]


def test_explicit_conscience_change_updates_only_the_requested_faculty(monkeypatch):
    written = []
    monkeypatch.setattr(auth_api.db, "get_user_details", lambda _user: {
        "intellect_model": "gpt-5.6-luna", "will_model": None,
        "conscience_model": "gemini-3.7-flash",
    })
    monkeypatch.setattr(auth_api.db, "update_user_models",
                        lambda _user, intellect, will, conscience:
                        written.append((intellect, will, conscience)))
    client = _client()
    with client.session_transaction() as session:
        session["user_id"] = "user-1"

    response = client.put("/api/me/models", json={"conscience_model": "jev-1.13.0"})

    assert response.status_code == 200
    assert written == [("gpt-5.6-luna", None, "jev-1.13.0")]
