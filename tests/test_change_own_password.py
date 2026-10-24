"""Self-service password change (POST /api/me/password).

Covers the temp-credential handover flow: a user who can authenticate with
the current password may replace it; nobody else can. OAuth/SCIM-only
identities must be refused (no password to change, and must not silently
gain an appliance credential).
"""
import pytest
from flask import Flask

from safi_app.api import auth as auth_api


def _make_app(user_row):
    app = Flask(__name__)
    app.secret_key = "test-session-secret"
    app.register_blueprint(auth_api.auth_bp, url_prefix="/api")

    @app.before_request
    def _seed_session():
        # Slim-session shape: user_id is only present mid-request for a
        # valid sid, which is exactly what change_my_password reads.
        from flask import session as flask_session
        flask_session["user_id"] = user_row["id"]

    app.testing = True
    return app.test_client()


@pytest.fixture
def user_row():
    from werkzeug.security import generate_password_hash
    return {"id": "u1", "username": "chepa", "email": None,
            "password_hash": generate_password_hash("temp-password-1")}


def _patch_db(monkeypatch, user_row):
    monkeypatch.setattr(auth_api.db, "get_user_details",
                        lambda uid: dict(user_row, id=uid) if uid == user_row["id"] else None)
    stored = {"hash": user_row["password_hash"]}
    monkeypatch.setattr(auth_api.db, "set_local_password",
                        lambda uid, pw: stored.update(
                            hash=__import__("werkzeug.security", fromlist=["x"])
                            .generate_password_hash(pw)) or True)
    return stored


def test_change_password_success(monkeypatch, user_row):
    from werkzeug.security import check_password_hash
    stored = _patch_db(monkeypatch, user_row)
    r = _make_app(user_row).post("/api/me/password", json={
        "current_password": "temp-password-1",
        "new_password": "my-brand-new-pass",
    })
    assert r.status_code == 200
    assert check_password_hash(stored["hash"], "my-brand-new-pass")


def test_wrong_current_password_rejected(monkeypatch, user_row):
    stored = _patch_db(monkeypatch, user_row)
    r = _make_app(user_row).post("/api/me/password", json={
        "current_password": "not-the-temp-password",
        "new_password": "my-brand-new-pass",
    })
    assert r.status_code == 403
    assert stored["hash"] == user_row["password_hash"]  # unchanged


def test_too_short_new_password(monkeypatch, user_row):
    _patch_db(monkeypatch, user_row)
    r = _make_app(user_row).post("/api/me/password", json={
        "current_password": "temp-password-1", "new_password": "short"})
    assert r.status_code == 400


def test_same_password_rejected(monkeypatch, user_row):
    _patch_db(monkeypatch, user_row)
    r = _make_app(user_row).post("/api/me/password", json={
        "current_password": "temp-password-1",
        "new_password": "temp-password-1"})
    assert r.status_code == 400


def test_oauth_account_refused(monkeypatch):
    app = Flask(__name__)
    app.secret_key = "t"
    app.register_blueprint(auth_api.auth_bp, url_prefix="/api")

    @app.before_request
    def _seed():
        from flask import session as s
        s["user_id"] = "u-oauth"
    monkeypatch.setattr(auth_api.db, "get_user_details",
                        lambda uid: {"id": uid, "email": "x@example.com",
                                     "username": None, "password_hash": None})
    app.testing = True
    r = app.test_client().post("/api/me/password", json={
        "current_password": "a", "new_password": "b"})
    assert r.status_code == 400


def test_anonymous_rejected():
    app = Flask(__name__)
    app.secret_key = "t"
    app.register_blueprint(auth_api.auth_bp, url_prefix="/api")
    app.testing = True
    r = app.test_client().post("/api/me/password", json={})
    assert r.status_code == 401
