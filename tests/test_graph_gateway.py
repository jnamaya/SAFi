"""
The Graph gateway: per-user Microsoft 365 tools (GOVERNANCE_BACKLOG 48k).

The OAuth core (PKCE, single-use codes, resource binding, Bearer validation)
is shared with the Workspace gateway and adversarially tested in
test_workspace_gateway.py; re-proving every refusal here would test the same
lines twice. What this suite pins is the Microsoft-shaped half plus one
end-to-end resource check that proves the core is actually wired in:

  * The whole triangle with SAFi's real client: discovery, registration, the
    authorize redirect to (a stub) Entra under the tenant path with read-only
    delegated scopes, the callback, the PKCE token exchange, and tool calls
    whose Graph requests carry the MICROSOFT token, never the SAFi-facing JWT.
  * Identity out of the id_token: sub becomes the subject,
    preferred_username fills in when email is absent, which is common on
    Entra work accounts.
  * The tools: files_search, file_get_contents (follows Graph's content
    route), sites_search, site_files_search.
  * The token endpoint still demands resource={gateway}/mcp (RFC 8707).
  * Microsoft refresh tokens are Fernet-encrypted at rest, ours are hashed.

Run:  python tests/test_graph_gateway.py
"""
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


MS_ACCESS = "ms-access-token-xyz"
MS_REFRESH = "ms-refresh-token-abc"


class _StubMicrosoft(BaseHTTPRequestHandler):
    """Entra's token endpoint and a few Graph APIs, canned. Records the
    Authorization header of every API GET, which is what lets a test
    distinguish "the gateway called Graph as the member" from "the gateway
    forwarded whatever it was given"."""

    api_auth_headers = []
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
        _StubMicrosoft.token_posts.append(form)
        if self.path == "/token":
            import base64
            # No "email" claim on purpose: work accounts often carry only
            # preferred_username, and the gateway must cope.
            id_payload = base64.urlsafe_b64encode(json.dumps(
                {"sub": "ms-sub-1", "preferred_username": "member@contoso.com"}
            ).encode()).rstrip(b"=").decode()
            return self._json({
                "access_token": MS_ACCESS,
                "refresh_token": MS_REFRESH,
                "expires_in": 3600,
                "id_token": f"h.{id_payload}.s",
            })
        return self._json({"error": "not found"}, 404)

    def do_GET(self):
        _StubMicrosoft.api_auth_headers.append(self.headers.get("Authorization", ""))
        # Specific routes before their generic prefixes, or the generic one
        # answers for both (the f123 lesson from the workspace suite).
        if self.path.startswith("/me/drive/items/f123/content"):
            body = b"Contract text body."
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/me/drive/items/f123"):
            return self._json({"name": "Contract.docx"})
        if self.path.startswith("/me/drive/root/search"):
            return self._json({"value": [
                {"name": "Q3 Plan.docx", "id": "f123",
                 "lastModifiedDateTime": "2026-08-10T00:00:00Z"},
            ]})
        if self.path.startswith("/sites/site-1/drive/root/search"):
            return self._json({"value": [
                {"name": "Policy.pdf", "id": "p1",
                 "lastModifiedDateTime": "2026-08-01T00:00:00Z"},
            ]})
        if self.path.startswith("/sites"):
            return self._json({"value": [
                {"displayName": "Finance", "id": "site-1",
                 "webUrl": "https://contoso.example/sites/finance"},
            ]})
        return self._json({"error": "not found"}, 404)


def _free_port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class GraphGatewayTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import uvicorn
        from cryptography.fernet import Fernet

        ms = ThreadingHTTPServer(("127.0.0.1", 0), _StubMicrosoft)
        threading.Thread(target=ms.serve_forever, daemon=True).start()
        cls.ms = ms
        ms_base = f"http://127.0.0.1:{ms.server_port}"

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
            "ENTRA_CLIENT_ID": "stub-entra-client",
            "ENTRA_CLIENT_SECRET": "stub-entra-secret",
            "MS_OAUTH_BASE": ms_base,
            "MS_TOKEN_URL": f"{ms_base}/token",
            "GRAPH_API_BASE": ms_base,
        }
        cls._saved_env = {k: os.environ.get(k) for k in env}
        os.environ.update(env)

        spec = importlib.util.spec_from_file_location(
            "graph_gateway",
            Path(__file__).resolve().parent.parent / "scripts" / "graph_gateway.py")
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

        cls.redirect_uri = "http://localhost:5000/api/mcp/auth/graph/callback"

    @classmethod
    def tearDownClass(cls):
        cls.uv.should_exit = True
        cls.thread.join(timeout=10)
        cls.ms.shutdown()
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

    def _run_flow(self):
        """Authorize -> stub Entra -> callback -> code, exactly as a browser
        would walk it."""
        import requests
        from safi_app.core.services import mcp_oauth

        discovery = self._discover()
        client_id = self._register(discovery)
        verifier, challenge = mcp_oauth.make_pkce()
        state = "safi-state-" + hashlib.sha1(verifier.encode()).hexdigest()[:8]

        url = mcp_oauth.build_authorization_url(
            discovery, client_id, self.redirect_uri, state, challenge)
        hop1 = requests.get(url, allow_redirects=False, timeout=5)
        self.assertEqual(hop1.status_code, 302, hop1.text)
        location = hop1.headers["Location"]
        # Entra under the tenant path, delegated read-only scopes, a refresh
        # token requested, and nothing writable.
        self.assertIn("/organizations/oauth2/v2.0/authorize", location)
        ms_q = {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}
        self.assertIn("offline_access", ms_q["scope"])
        self.assertIn("Files.Read.All", ms_q["scope"])
        self.assertNotIn("ReadWrite", ms_q["scope"])

        hop2 = requests.get(
            f"{self.base}/microsoft/callback?code=mcode&state={ms_q['state']}",
            allow_redirects=False, timeout=5)
        self.assertEqual(hop2.status_code, 302, hop2.text)
        back = {k: v[0] for k, v in
                parse_qs(urlparse(hop2.headers["Location"]).query).items()}
        self.assertEqual(back["state"], state, "state must round-trip untouched")
        return back["code"], verifier, client_id, discovery

    def _token(self):
        from safi_app.core.services import mcp_oauth
        code, verifier, client_id, discovery = self._run_flow()
        body = mcp_oauth.exchange_code(
            discovery, {"client_id": client_id, "client_secret": ""},
            code, self.redirect_uri, verifier)
        return body, discovery, client_id

    # ── the triangle, on the wire ─────────────────────────────────────────────

    def test_the_whole_triangle_with_safis_own_client(self):
        import asyncio
        from safi_app.core import mcp_runtime
        body, _, _ = self._token()
        self.assertIn("access_token", body)
        self.assertIn("refresh_token", body)

        out = asyncio.run(mcp_runtime.call_with_token(
            self.resource_uri, "microsoft_whoami", {}, body["access_token"]))
        # preferred_username filled in for the absent email claim.
        self.assertIn("member@contoso.com", out)

        _StubMicrosoft.api_auth_headers.clear()
        out = asyncio.run(mcp_runtime.call_with_token(
            self.resource_uri, "files_search", {"query": "Q3"},
            body["access_token"]))
        self.assertIn("Q3 Plan.docx", out)
        # The no-passthrough rule, observed: Graph saw the MICROSOFT token,
        # and at no point the SAFi-facing JWT.
        self.assertIn(f"Bearer {MS_ACCESS}", _StubMicrosoft.api_auth_headers)
        for header in _StubMicrosoft.api_auth_headers:
            self.assertNotIn(body["access_token"], header)

    def test_file_contents_and_site_tools_answer(self):
        import asyncio
        from safi_app.core import mcp_runtime
        body, _, _ = self._token()

        contents = asyncio.run(mcp_runtime.call_with_token(
            self.resource_uri, "file_get_contents", {"item_id": "f123"},
            body["access_token"]))
        self.assertIn("Contract.docx", contents)
        self.assertIn("Contract text body.", contents)

        sites = asyncio.run(mcp_runtime.call_with_token(
            self.resource_uri, "sites_search", {"query": "finance"},
            body["access_token"]))
        self.assertIn("Finance", sites)
        self.assertIn("site-1", sites)

        site_files = asyncio.run(mcp_runtime.call_with_token(
            self.resource_uri, "site_files_search",
            {"site_id": "site-1", "query": "policy"}, body["access_token"]))
        self.assertIn("Policy.pdf", site_files)

    def test_refresh_grant_mints_a_working_token(self):
        import asyncio
        from safi_app.core import mcp_runtime
        from safi_app.core.services import mcp_oauth
        body, discovery, client_id = self._token()
        refreshed = mcp_oauth.refresh(
            discovery, {"client_id": client_id, "client_secret": ""},
            body["refresh_token"])
        out = asyncio.run(mcp_runtime.call_with_token(
            self.resource_uri, "microsoft_whoami", {}, refreshed["access_token"]))
        self.assertIn("member@contoso.com", out)

    # ── the core is wired in, not just imported ──────────────────────────────

    def test_the_token_endpoint_demands_the_right_resource(self):
        import requests
        code, verifier, client_id, _ = self._run_flow()
        resp = requests.post(f"{self.base}/token", data={
            "grant_type": "authorization_code", "code": code,
            "client_id": client_id, "redirect_uri": self.redirect_uri,
            "code_verifier": verifier,
            "resource": "https://some-other-service.example/api",
        }, timeout=5)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "invalid_target")

    # ── at-rest properties ────────────────────────────────────────────────────

    def test_microsoft_refresh_tokens_are_encrypted_and_ours_are_hashed(self):
        body, _, _ = self._token()

        conn = sqlite3.connect(self.db_path)
        # The upstream-token table kept its original name when gateway_core
        # was extracted, so live Workspace databases survive the refactor; on
        # a Graph gateway it holds Microsoft tokens. See the Store docstring.
        ms_rows = conn.execute(
            "SELECT refresh_token_enc FROM google_tokens").fetchall()
        our_rows = conn.execute("SELECT token_hash FROM refresh_tokens").fetchall()
        conn.close()

        self.assertTrue(ms_rows)
        for (enc,) in ms_rows:
            self.assertNotIn(MS_REFRESH, enc or "")
        expected = hashlib.sha256(body["refresh_token"].encode()).hexdigest()
        self.assertIn((expected,), our_rows)
        for (stored,) in our_rows:
            self.assertNotEqual(stored, body["refresh_token"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
