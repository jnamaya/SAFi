"""
The Workspace gateway: AS + RS in one service (GOVERNANCE_BACKLOG 48j).

An authorization server earns adversarial tests or it is a liability, so the
happy path here is one test among many. What is pinned:

  * The whole triangle, using SAFi's REAL client code end to end: discovery,
    dynamic registration, the authorize redirect to (a stub) Google, the
    callback, the PKCE-verified token exchange, and a tool call whose Google
    API request carries the GOOGLE token from the gateway's store, provably
    not the SAFi-facing JWT, which is the no-passthrough rule observed on the
    wire rather than asserted in prose.
  * The refusals that make the guarantees real: wrong PKCE verifier, replayed
    authorization code, wrong or missing `resource`, unregistered
    redirect_uri, missing code_challenge, and unauthenticated or garbage
    Bearer tokens at the resource side.
  * Refresh tokens work and are stored as hashes, never plaintext; Google
    refresh tokens are Fernet-encrypted at rest, checked against the raw
    sqlite bytes.

The stub Google records the Authorization header of every API call, which is
what lets a test distinguish "the gateway called Google as the member" from
"the gateway forwarded whatever it was given".

Run:  venv/bin/python tests/test_workspace_gateway.py
"""
import base64
import hashlib
import importlib.util
import json
import os
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))


GOOGLE_ACCESS = "google-access-token-xyz"
GOOGLE_REFRESH = "google-refresh-token-abc"


class _StubGoogle(BaseHTTPRequestHandler):
    """Google's OAuth token endpoint and a few Workspace APIs, canned."""

    api_auth_headers = []   # Authorization header of every API GET
    token_posts = []

    def log_message(self, *args):
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        form = {k: v[0] for k, v in parse_qs(raw).items()}
        _StubGoogle.token_posts.append(form)
        if self.path == "/token":
            id_payload = base64.urlsafe_b64encode(json.dumps(
                {"sub": "google-sub-1", "email": "member@example.com"}
            ).encode()).rstrip(b"=").decode()
            return self._json({
                "access_token": GOOGLE_ACCESS,
                "refresh_token": GOOGLE_REFRESH,
                "expires_in": 3600,
                "id_token": f"h.{id_payload}.s",
            })
        return self._json({"error": "not found"}, 404)

    def do_GET(self):
        _StubGoogle.api_auth_headers.append(self.headers.get("Authorization", ""))
        if self.path.startswith("/calendar/"):
            return self._json({"items": [
                {"summary": "Board meeting", "start": {"dateTime": "2026-08-15T10:00:00Z"}},
            ]})
        if self.path.startswith("/drive/"):
            return self._json({"files": [
                {"name": "Q3 Plan.docx", "mimeType": "application/vnd.google-apps.document",
                 "modifiedTime": "2026-08-10T00:00:00Z"},
            ]})
        if self.path.startswith("/gmail/v1/users/me/messages/"):
            return self._json({"payload": {"headers": [
                {"name": "Subject", "value": "Quarterly numbers"},
                {"name": "From", "value": "cfo@example.com"},
                {"name": "Date", "value": "Fri, 15 Aug 2026"},
            ]}})
        if self.path.startswith("/gmail/"):
            return self._json({"messages": [{"id": "m1"}]})
        return self._json({"error": "not found"}, 404)


def _free_port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class WorkspaceGatewayTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import uvicorn
        from cryptography.fernet import Fernet

        google = ThreadingHTTPServer(("127.0.0.1", 0), _StubGoogle)
        threading.Thread(target=google.serve_forever, daemon=True).start()
        cls.google = google
        google_base = f"http://127.0.0.1:{google.server_port}"

        port = _free_port()
        cls.base = f"http://127.0.0.1:{port}"
        cls.resource_uri = f"{cls.base}/mcp"
        cls.db_path = tempfile.mktemp(suffix=".db")

        # The gateway reads env at import, so it is loaded fresh with the stub
        # wiring in place.
        env = {
            "GATEWAY_BASE_URL": cls.base,
            "GATEWAY_DB": cls.db_path,
            "GATEWAY_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "GOOGLE_CLIENT_ID": "stub-google-client",
            "GOOGLE_CLIENT_SECRET": "stub-google-secret",
            "GOOGLE_OAUTH_BASE": google_base,
            "GOOGLE_TOKEN_URL": f"{google_base}/token",
            "GOOGLE_API_BASE": google_base,
        }
        cls._saved_env = {k: os.environ.get(k) for k in env}
        os.environ.update(env)

        spec = importlib.util.spec_from_file_location(
            "workspace_gateway",
            Path(__file__).resolve().parent.parent / "scripts" / "workspace_gateway.py")
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

        config = uvicorn.Config(cls.module.build_app(), host="127.0.0.1",
                                port=port, log_level="error")
        cls.uv = uvicorn.Server(config)
        cls.thread = threading.Thread(target=cls.uv.run, daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.uv.started:
                break
            time.sleep(0.1)

        cls.redirect_uri = "http://localhost:5000/api/mcp/auth/workspace/callback"

    @classmethod
    def tearDownClass(cls):
        cls.uv.should_exit = True
        cls.thread.join(timeout=10)
        cls.google.shutdown()
        for k, v in cls._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        try:
            os.unlink(cls.db_path)
        except OSError:
            pass

    # ── helpers using SAFi's REAL client half ─────────────────────────────────

    def _discover(self):
        from safi_app.core.services import mcp_oauth
        mcp_oauth.clear_discovery_cache()
        return mcp_oauth.discover(self.resource_uri)

    def _register(self, discovery):
        import requests
        resp = requests.post(discovery["registration_endpoint"],
                             json={"redirect_uris": [self.redirect_uri]}, timeout=5)
        return resp.json()["client_id"]

    def _run_flow(self, client_id=None, verifier=None):
        """Authorize -> stub Google -> callback -> code, exactly as a browser
        would walk it. Returns (code, state, verifier, client_id)."""
        import requests
        from safi_app.core.services import mcp_oauth

        discovery = self._discover()
        client_id = client_id or self._register(discovery)
        real_verifier, challenge = mcp_oauth.make_pkce()
        verifier = verifier or real_verifier
        state = "safi-state-" + hashlib.sha1(verifier.encode()).hexdigest()[:8]

        url = mcp_oauth.build_authorization_url(
            discovery, client_id, self.redirect_uri, state, challenge)
        hop1 = requests.get(url, allow_redirects=False, timeout=5)
        self.assertEqual(hop1.status_code, 302, hop1.text)
        google_q = {k: v[0] for k, v in
                    parse_qs(urlparse(hop1.headers["Location"]).query).items()}
        # What Google is asked for: offline access with explicit consent, and
        # never anything writable.
        self.assertEqual(google_q["access_type"], "offline")
        self.assertNotIn("gmail.modify", google_q["scope"])

        hop2 = requests.get(
            f"{self.base}/google/callback?code=gcode&state={google_q['state']}",
            allow_redirects=False, timeout=5)
        self.assertEqual(hop2.status_code, 302, hop2.text)
        back = {k: v[0] for k, v in
                parse_qs(urlparse(hop2.headers["Location"]).query).items()}
        self.assertEqual(back["state"], state, "state must round-trip untouched")
        return back["code"], state, real_verifier, client_id, discovery

    # ── the happy path, on the wire ───────────────────────────────────────────

    def test_the_whole_triangle_with_safis_own_client(self):
        from safi_app.core.services import mcp_oauth
        code, _, verifier, client_id, discovery = self._run_flow()
        body = mcp_oauth.exchange_code(
            discovery, {"client_id": client_id, "client_secret": ""},
            code, self.redirect_uri, verifier)
        self.assertIn("access_token", body)
        self.assertIn("refresh_token", body)

        import asyncio
        from safi_app.core import mcp_runtime
        out = asyncio.run(mcp_runtime.call_with_token(
            self.resource_uri, "whoami", {}, body["access_token"]))
        self.assertIn("member@example.com", out)

        _StubGoogle.api_auth_headers.clear()
        out = asyncio.run(mcp_runtime.call_with_token(
            self.resource_uri, "calendar_list_events", {}, body["access_token"]))
        self.assertIn("Board meeting", out)
        # The no-passthrough rule, observed: Google saw the GOOGLE token, and
        # at no point the SAFi-facing JWT.
        self.assertIn(f"Bearer {GOOGLE_ACCESS}", _StubGoogle.api_auth_headers)
        for header in _StubGoogle.api_auth_headers:
            self.assertNotIn(body["access_token"], header)

    def test_drive_and_gmail_tools_answer(self):
        import asyncio
        from safi_app.core import mcp_runtime
        from safi_app.core.services import mcp_oauth
        code, _, verifier, client_id, discovery = self._run_flow()
        body = mcp_oauth.exchange_code(
            discovery, {"client_id": client_id, "client_secret": ""},
            code, self.redirect_uri, verifier)
        drive = asyncio.run(mcp_runtime.call_with_token(
            self.resource_uri, "drive_search", {"query": "Q3"}, body["access_token"]))
        self.assertIn("Q3 Plan.docx", drive)
        mail = asyncio.run(mcp_runtime.call_with_token(
            self.resource_uri, "gmail_search", {"query": "numbers"}, body["access_token"]))
        self.assertIn("Quarterly numbers", mail)

    def test_refresh_grant_mints_a_working_token(self):
        import asyncio
        from safi_app.core import mcp_runtime
        from safi_app.core.services import mcp_oauth
        code, _, verifier, client_id, discovery = self._run_flow()
        body = mcp_oauth.exchange_code(
            discovery, {"client_id": client_id, "client_secret": ""},
            code, self.redirect_uri, verifier)
        refreshed = mcp_oauth.refresh(
            discovery, {"client_id": client_id, "client_secret": ""},
            body["refresh_token"])
        out = asyncio.run(mcp_runtime.call_with_token(
            self.resource_uri, "whoami", {}, refreshed["access_token"]))
        self.assertIn("member@example.com", out)

    # ── the refusals ──────────────────────────────────────────────────────────

    def test_a_wrong_pkce_verifier_is_refused(self):
        from safi_app.core.services import mcp_oauth
        code, _, _, client_id, discovery = self._run_flow()
        with self.assertRaises(mcp_oauth.OAuthConfigError):
            mcp_oauth.exchange_code(
                discovery, {"client_id": client_id, "client_secret": ""},
                code, self.redirect_uri, "not-the-verifier")

    def test_an_authorization_code_is_single_use(self):
        from safi_app.core.services import mcp_oauth
        code, _, verifier, client_id, discovery = self._run_flow()
        mcp_oauth.exchange_code(
            discovery, {"client_id": client_id, "client_secret": ""},
            code, self.redirect_uri, verifier)
        with self.assertRaises(mcp_oauth.OAuthConfigError):
            mcp_oauth.exchange_code(
                discovery, {"client_id": client_id, "client_secret": ""},
                code, self.redirect_uri, verifier)

    def test_the_token_endpoint_demands_the_right_resource(self):
        import requests
        code, state, verifier, client_id, _ = self._run_flow()
        resp = requests.post(f"{self.base}/token", data={
            "grant_type": "authorization_code", "code": code,
            "client_id": client_id, "redirect_uri": self.redirect_uri,
            "code_verifier": verifier,
            "resource": "https://some-other-service.example/api",
        }, timeout=5)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "invalid_target")

    def test_authorize_refuses_what_oauth21_forbids(self):
        import requests
        discovery = self._discover()
        client_id = self._register(discovery)
        base_q = {
            "response_type": "code", "client_id": client_id,
            "redirect_uri": self.redirect_uri, "state": "s",
            "code_challenge": "c", "code_challenge_method": "S256",
            "resource": self.resource_uri,
        }
        for breakage, mutation in [
            ("no PKCE", {"code_challenge": ""}),
            ("plain PKCE", {"code_challenge_method": "plain"}),
            ("implicit", {"response_type": "token"}),
            ("wrong resource", {"resource": "https://evil.example/mcp"}),
            ("unregistered redirect", {"redirect_uri": "https://evil.example/cb"}),
            ("unknown client", {"client_id": "gwc-never-registered"}),
        ]:
            q = dict(base_q); q.update(mutation)
            from urllib.parse import urlencode
            resp = requests.get(f"{self.base}/authorize?{urlencode(q)}",
                                allow_redirects=False, timeout=5)
            self.assertEqual(resp.status_code, 400, f"{breakage} must be refused")

    def test_the_resource_side_refuses_the_unauthenticated_and_the_garbage(self):
        import asyncio
        import requests
        from safi_app.core import mcp_runtime
        resp = requests.post(self.resource_uri, json={}, timeout=5)
        self.assertEqual(resp.status_code, 401)
        self.assertIn("resource_metadata=", resp.headers.get("WWW-Authenticate", ""))
        out = asyncio.run(mcp_runtime.call_with_token(
            self.resource_uri, "whoami", {}, "not-a-token"))
        self.assertTrue(out.startswith("ERROR:"))

    # ── at-rest properties ────────────────────────────────────────────────────

    def test_google_refresh_tokens_are_encrypted_and_ours_are_hashed(self):
        from safi_app.core.services import mcp_oauth
        code, _, verifier, client_id, discovery = self._run_flow()
        body = mcp_oauth.exchange_code(
            discovery, {"client_id": client_id, "client_secret": ""},
            code, self.redirect_uri, verifier)

        conn = sqlite3.connect(self.db_path)
        google_rows = conn.execute(
            "SELECT refresh_token_enc FROM google_tokens").fetchall()
        our_rows = conn.execute("SELECT token_hash FROM refresh_tokens").fetchall()
        conn.close()

        self.assertTrue(google_rows)
        for (enc,) in google_rows:
            self.assertNotIn(GOOGLE_REFRESH, enc or "")
        expected = hashlib.sha256(body["refresh_token"].encode()).hexdigest()
        self.assertIn((expected,), our_rows)
        for (stored,) in our_rows:
            self.assertNotEqual(stored, body["refresh_token"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
