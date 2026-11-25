import pathlib
from unittest.mock import patch

import pytest
from flask import Flask, jsonify
from werkzeug.security import check_password_hash

from safi_app.api import auth as auth_mod
from safi_app.config import Config


def test_dummy_password_hash_is_valid_werkzeug_pbkdf2():
    assert auth_mod._DUMMY_PASSWORD_HASH.startswith("pbkdf2:sha256:")
    assert check_password_hash(auth_mod._DUMMY_PASSWORD_HASH, "any-password") is False


def test_unknown_user_login_runs_dummy_password_hash_without_error(monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(auth_mod.auth_bp, url_prefix="/api")

    monkeypatch.setattr(Config, "password_login_available", classmethod(lambda cls: True))
    monkeypatch.setattr(auth_mod.db, "get_user_by_identifier", lambda _id: None)

    checked = []

    def _spy_check(pwhash, password):
        checked.append((pwhash, password))
        return check_password_hash(pwhash, password)

    with patch("werkzeug.security.check_password_hash", side_effect=_spy_check):
        client = app.test_client()
        resp = client.post(
            "/api/login/local",
            json={"identifier": "nobody@example.com", "password": "wrong-password"},
        )

    assert resp.status_code == 401
    assert resp.get_json() == {"error": "Invalid credentials."}
    assert len(checked) == 1
    assert checked[0][0] == auth_mod._DUMMY_PASSWORD_HASH


def test_bot_api_secret_has_no_hardcoded_default():
    src = pathlib.Path("safi_app/config.py").read_text(encoding="utf-8")
    assert 'os.environ.get("SAFI_BOT_API_SECRET", "")' in src


def test_conversations_has_no_md5():
    src = pathlib.Path("safi_app/api/conversations.py").read_text(encoding="utf-8")
    assert "hashlib.md5" not in src


def test_mfa_rate_limit_uses_shared_store_with_fallback(monkeypatch):
    from safi_app.persistence import rate_limit_store

    calls = []
    monkeypatch.setattr(
        rate_limit_store,
        "is_rate_limited",
        lambda bucket, max_a, win: (calls.append(("check", bucket, max_a, win)) or True),
    )
    assert auth_mod._mfa_rate_limited("u-123") is True
    assert calls[0][1] == "mfa:u-123"

    # Fallback to in-memory when DB store returns None/False
    auth_mod._mfa_attempts.clear()
    monkeypatch.setattr(rate_limit_store, "is_rate_limited", lambda *a, **kw: None)
    monkeypatch.setattr(rate_limit_store, "record_attempt", lambda *a, **kw: False)
    monkeypatch.setattr(rate_limit_store, "clear_attempts", lambda *a, **kw: False)

    for _ in range(auth_mod._MFA_MAX_ATTEMPTS):
        assert auth_mod._mfa_rate_limited("u-fallback") is False
        auth_mod._mfa_record_attempt("u-fallback")
    assert auth_mod._mfa_rate_limited("u-fallback") is True
    auth_mod._mfa_clear_attempts("u-fallback")
    assert auth_mod._mfa_rate_limited("u-fallback") is False


def test_csrf_origin_guard_blocks_cross_site_and_allows_legitimate():
    from safi_app import create_app

    with patch.object(Config, "validate", return_value=None), \
         patch("safi_app.core.integrity.enforce_at_boot", return_value=None), \
         patch("safi_app.core.services.mcp_manager.start_servers", return_value={"servers": {}, "tool_count": 0}), \
         patch("safi_app.persistence.database.init_db", return_value=None), \
         patch("safi_app.persistence.incident_store.init_schema", return_value=None), \
         patch("safi_app.persistence.demo_store.init_demo_usage_schema", return_value=None), \
         patch("safi_app.persistence.mcp_store.init_schema", return_value=None), \
         patch("safi_app.persistence.sharing_store.init_schema", return_value=None), \
         patch("safi_app.persistence.conversation_sharing_store.init_schema", return_value=None), \
         patch("safi_app.persistence.tool_approval_store.init_schema", return_value=None), \
         patch("safi_app.persistence.scim_store.init_schema", return_value=None), \
         patch("safi_app.persistence.rate_limit_store.init_schema", return_value=None), \
         patch("safi_app.bootstrap.initialize", return_value=None), \
         patch("safi_app.core.services.mcp_manager.resync_if_stale", return_value=None), \
         patch("safi_app.core.identity.resolve_session", return_value=None):
        app = create_app()

        @app.route("/api/_test_csrf_probe", methods=["POST"])
        def _probe():
            return jsonify({"ok": True})

        client = app.test_client()
        client.set_cookie("safi_session", "fake-cookie")

        # Cross-site Origin -> 403
        r_evil = client.post("/api/_test_csrf_probe", headers={"Origin": "https://evil.example"})
        assert r_evil.status_code == 403

        # Cross-site Referer -> 403
        r_evil_ref = client.post("/api/_test_csrf_probe", headers={"Referer": "https://evil.example/page"})
        assert r_evil_ref.status_code == 403

        # Cross-site Sec-Fetch-Site -> 403
        r_evil_sfs = client.post("/api/_test_csrf_probe", headers={"Sec-Fetch-Site": "cross-site"})
        assert r_evil_sfs.status_code == 403

        # Same-origin -> 200
        r_ok = client.post("/api/_test_csrf_probe", headers={"Origin": "http://localhost"})
        assert r_ok.status_code == 200

        # Bearer Authorization bypasses cookie CSRF check -> 200
        r_bearer = client.post(
            "/api/_test_csrf_probe",
            headers={"Origin": "https://evil.example", "Authorization": "Bearer test-token"},
        )
        assert r_bearer.status_code == 200


def test_jwt_domain_separation_and_invite_expiry_cap():
    mfa_tok = auth_mod._issue_mfa_token("u-1")
    inv_tok = auth_mod.issue_invite_claim_token("inv-1", "a@b.com", 365)

    assert auth_mod._verify_mfa_token(mfa_tok) == "u-1"
    assert auth_mod.verify_invite_claim_token(inv_tok) == {"invite_id": "inv-1", "email": "a@b.com"}
    # Cross-domain verification must fail
    assert auth_mod._verify_mfa_token(inv_tok) is None
    assert auth_mod.verify_invite_claim_token(mfa_tok) is None

    # Invite token expiry must be capped at _MAX_INVITE_EXPIRES_DAYS (30)
    import jwt, time
    decoded = jwt.decode(inv_tok, auth_mod._signing_key("invite_claim"), algorithms=["HS256"])
    assert decoded["exp"] - time.time() <= (auth_mod._MAX_INVITE_EXPIRES_DAYS * 86400) + 60


def test_mcp_oauth_blocks_ssrf_urls():
    from safi_app.core.services import mcp_oauth
    for bad in ("file:///etc/passwd", "https://169.254.169.254/latest", "https://user:pass@example.com/token"):
        with pytest.raises(mcp_oauth.OAuthConfigError):
            mcp_oauth._assert_safe_url(bad)


def test_compose_and_entrypoint_hardening():
    compose = pathlib.Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "rootpassword" not in compose
    assert "MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:?" in compose
    assert "no-new-privileges:true" in compose

    entry = pathlib.Path("docker-entrypoint.sh").read_text(encoding="utf-8")
    assert "<<'EOF'" in entry
    assert 'password="${DB_PASSWORD}"' not in entry
