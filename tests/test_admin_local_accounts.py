"""Admin-provisioned local (appliance) accounts: creation + password reset."""
from flask import Flask, session

from safi_app.api import organizations as orgs_api


def _client(role="admin"):
    app = Flask(__name__)
    app.secret_key = "test-session-secret"
    app.config["ROLE_CONFIG"] = {"levels": {"admin": 3, "editor": 2, "auditor": 1, "member": 0},
                                 "default_role": "member"}
    app.register_blueprint(orgs_api.organizations_bp, url_prefix="/api")
    app.testing = True
    client = app.test_client()
    with client.session_transaction() as s:
        s["user"] = {"id": "admin-1", "role": role, "org_id": "org-1"}
    return client


def test_create_local_account_returns_one_time_password(monkeypatch):
    logs, created = [], {}
    monkeypatch.setattr(orgs_api.db, "create_local_account",
                        lambda u, p, name=None, org_id=None, role=None:
                        created.update(user_id="u1", username=u) or dict(created))
    monkeypatch.setattr(orgs_api.db, "append_compliance_log",
                        lambda *a, **k: logs.append(a))

    r = _client().post("/api/organizations/org-1/members/local",
                       json={"username": "nelson", "name": "Nelson", "role": "member"})

    assert r.status_code == 201
    body = r.get_json()
    assert body["username"] == "nelson"
    # Server-generated credential handed back exactly once.
    assert len(body["initial_password"]) >= 20
    assert logs and logs[0][1] == "local_account_created"


def test_create_rejects_taken_username(monkeypatch):
    monkeypatch.setattr(orgs_api.db, "create_local_account",
                        lambda *a, **k: None)
    r = _client().post("/api/organizations/org-1/members/local",
                       json={"username": "taken"})
    assert r.status_code == 409


def test_create_rejects_bad_role(monkeypatch):
    r = _client().post("/api/organizations/org-1/members/local",
                       json={"username": "okuser", "role": "superuser"})
    assert r.status_code == 400


def test_create_forbidden_for_other_org():
    r = _client().post("/api/organizations/org-OTHER/members/local",
                       json={"username": "okuser"})
    assert r.status_code == 403


def test_create_forbidden_for_non_admin():
    r = _client(role="member").post("/api/organizations/org-1/members/local",
                                    json={"username": "okuser"})
    assert r.status_code == 403


def test_password_reset_returns_fresh_password(monkeypatch):
    logs = []
    monkeypatch.setattr(orgs_api.db, "reset_local_account_password",
                        lambda uid, pw: uid == "u1")
    monkeypatch.setattr(orgs_api.db, "append_compliance_log",
                        lambda *a, **k: logs.append(a))
    r = _client().post("/api/organizations/org-1/members/u1/password")
    assert r.status_code == 200
    assert len(r.get_json()["initial_password"]) >= 20
    assert logs and logs[0][1] == "local_password_reset"


def test_password_reset_404_for_non_local_account(monkeypatch):
    monkeypatch.setattr(orgs_api.db, "reset_local_account_password",
                        lambda uid, pw: False)
    r = _client().post("/api/organizations/org-1/members/oauth-only/password")
    assert r.status_code == 404
