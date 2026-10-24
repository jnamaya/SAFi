"""Regression: /api/me must honor g.user hydrated by identity.resolve_session.

The slim session cookie carries only 'sid'; session['user_id'] exists only
mid-request. get_me previously read session.get('user_id') directly, so a
freshly-created local-account session looked anonymous and the frontend fell
into its 'session could not be established' branch.
"""
from flask import Flask, g

from safi_app.api import auth as auth_api


def _client(user_row):
    app = Flask(__name__)
    app.secret_key = "test-session-secret"
    app.register_blueprint(auth_api.auth_bp, url_prefix="/api")

    @app.before_request
    def _hydrate():
        g.user = user_row  # what resolve_session would set for a valid sid

    app.testing = True
    return app.test_client()


def test_me_honors_hydrated_g_user(monkeypatch):
    row = {"id": "u1", "email": None, "username": "nelson", "name": "Nelson",
           "active_profile": None, "role": "member", "org_id": None}
    monkeypatch.setattr(auth_api.db, "get_user_details", lambda uid: dict(row, id=uid))
    monkeypatch.setattr(auth_api, "get_profile",
                        lambda name: {"name": name})

    r = _client(row).get("/api/me")
    assert r.status_code == 200
    assert r.get_json()["user"]["username"] == "nelson"


def test_me_anonymous_without_session_or_g():
    app = Flask(__name__)
    app.secret_key = "test-session-secret"
    app.register_blueprint(auth_api.auth_bp, url_prefix="/api")
    app.testing = True
    r = app.test_client().get("/api/me")
    assert r.status_code == 401
