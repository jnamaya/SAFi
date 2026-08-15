"""
OAuth 2.1 for MCP tool servers (GOVERNANCE_BACKLOG 48i).

What is pinned here, and why each item earns a test:

  * PKCE is S256 and the derivation is exactly RFC 7636's — a subtle slip in
    base64url padding produces challenges some ASes accept and others refuse,
    which debugging from the outside looks like a broken IdP.
  * `resource` (RFC 8707) is sent at BOTH the authorization and token
    endpoints. This parameter is the no-passthrough rule made concrete: it is
    what binds the minted token's audience to the MCP server, so its absence
    would not fail loudly — it would quietly produce tokens with the wrong or
    no audience, which a strict server refuses and a sloppy one accepts.
  * Discovery walks PRM (RFC 9728) then AS metadata (RFC 8414, with the OIDC
    fallback), and failures name which half broke.
  * Dynamic registration happens once and is reused, not once per login.
  * The Flask routes: login redirects with the right parameters, the callback
    refuses a state mismatch and a guest, and a good callback stores an
    ENCRYPTED token row.
  * End to end against a real Bearer-protected MCP server (uvicorn, in
    process): a call with the right token executes and returns; a call with a
    bad token comes back as a reconnect message, not a stack trace.

The stub AS/PRM server records every request body so the assertions are on
what was actually sent over the wire, not on what our code intended to send.

Run:  venv/bin/python tests/test_mcp_oauth.py
"""
import base64
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from safi_app.core.services import mcp_oauth


# ── A stub IdP + protected-resource metadata host ─────────────────────────────

class _StubHandler(BaseHTTPRequestHandler):
    calls = []          # (path, form_dict) for POSTs
    register_count = 0

    def log_message(self, *args):
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    jwks = {"keys": []}

    def do_GET(self):
        base = f"http://127.0.0.1:{self.server.server_port}"
        if self.path == "/jwks":
            return self._json(_StubHandler.jwks)
        if self.path.startswith("/.well-known/oauth-protected-resource"):
            return self._json({
                "resource": f"{base}/mcp",
                "authorization_servers": [base],
                "scopes_supported": ["tools.read"],
            })
        if self.path.startswith("/.well-known/oauth-authorization-server"):
            return self._json({
                "issuer": base,
                "authorization_endpoint": f"{base}/authorize",
                "token_endpoint": f"{base}/token",
                "registration_endpoint": f"{base}/register",
            })
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode()
        if self.path == "/register":
            _StubHandler.register_count += 1
            _StubHandler.calls.append(("/register", json.loads(raw or "{}")))
            return self._json({"client_id": "safi-test-client"}, 201)
        if self.path == "/token":
            form = {k: v[0] for k, v in parse_qs(raw).items()}
            _StubHandler.calls.append(("/token", form))
            if form.get("grant_type") == "authorization_code" and form.get("code") != "good-code":
                return self._json({"error": "invalid_grant"}, 400)
            return self._json({
                "access_token": f"at-{form.get('grant_type')}-{int(time.time())}",
                "refresh_token": "rt-1",
                "expires_in": 3600,
                "token_type": "Bearer",
            })
        return self._json({"error": "not found"}, 404)


def _start_stub():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


class PkceTests(unittest.TestCase):
    def test_challenge_is_s256_of_the_verifier(self):
        verifier, challenge = mcp_oauth.make_pkce()
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, expected)
        self.assertNotIn("=", challenge)
        self.assertGreaterEqual(len(verifier), 43)

    def test_every_flow_gets_a_fresh_pair(self):
        self.assertNotEqual(mcp_oauth.make_pkce()[0], mcp_oauth.make_pkce()[0])


class DiscoveryAndFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.base = _start_stub()
        cls.resource_url = f"{cls.base}/mcp"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        mcp_oauth.clear_discovery_cache()
        _StubHandler.calls = []

    def test_discovery_resolves_prm_then_as_metadata(self):
        d = mcp_oauth.discover(self.resource_url)
        self.assertEqual(d["resource"], self.resource_url)
        self.assertEqual(d["authorization_endpoint"], f"{self.base}/authorize")
        self.assertEqual(d["token_endpoint"], f"{self.base}/token")
        self.assertIn("tools.read", d["scopes_supported"])

    def test_a_server_with_no_prm_names_that_as_the_problem(self):
        with self.assertRaises(mcp_oauth.OAuthConfigError) as ctx:
            mcp_oauth.discover("https://this-name-should-not-resolve.invalid/mcp")
        self.assertIn("protected-resource", str(ctx.exception))

    def test_authorization_url_carries_the_spec(self):
        d = mcp_oauth.discover(self.resource_url)
        url = mcp_oauth.build_authorization_url(
            d, "client-1", "https://safi.example/cb", "state-1", "challenge-1")
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        self.assertEqual(q["response_type"], "code")   # never implicit
        self.assertEqual(q["code_challenge_method"], "S256")
        self.assertEqual(q["code_challenge"], "challenge-1")
        # RFC 8707: the audience request. THE parameter of this architecture.
        self.assertEqual(q["resource"], self.resource_url)
        self.assertEqual(q["state"], "state-1")

    def test_token_exchange_sends_verifier_and_resource(self):
        d = mcp_oauth.discover(self.resource_url)
        body = mcp_oauth.exchange_code(
            d, {"client_id": "client-1", "client_secret": ""},
            "good-code", "https://safi.example/cb", "verifier-xyz")
        self.assertIn("access_token", body)
        path, form = [c for c in _StubHandler.calls if c[0] == "/token"][-1]
        self.assertEqual(form["code_verifier"], "verifier-xyz")
        self.assertEqual(form["resource"], self.resource_url)
        self.assertEqual(form["grant_type"], "authorization_code")

    def test_a_configured_secret_travels_in_the_body_not_basic_auth(self):
        """GitHub's token endpoint accepts the secret only as a form field, and
        RFC 6749 permits it, so the body is the shape that works everywhere."""
        import os
        d = mcp_oauth.discover(self.resource_url)
        os.environ["MCP_TEST_SECRET"] = "s3cr3t-from-env"
        try:
            mcp_oauth.exchange_code(
                d,
                mcp_oauth.ensure_client_readonly(
                    "any", {"client_id": "cid-1",
                            "client_secret": "${MCP_TEST_SECRET}"}, d),
                "good-code", "https://safi.example/cb", "v")
        finally:
            os.environ.pop("MCP_TEST_SECRET", None)
        path, form = [c for c in _StubHandler.calls if c[0] == "/token"][-1]
        self.assertEqual(form["client_secret"], "s3cr3t-from-env",
                         "the ${VAR} reference must resolve from the environment")
        self.assertEqual(form["client_id"], "cid-1")

    def test_a_bad_code_is_a_clean_error(self):
        d = mcp_oauth.discover(self.resource_url)
        with self.assertRaises(mcp_oauth.OAuthConfigError):
            mcp_oauth.exchange_code(
                d, {"client_id": "c", "client_secret": ""},
                "wrong-code", "https://safi.example/cb", "v")

    def test_refresh_also_carries_resource(self):
        d = mcp_oauth.discover(self.resource_url)
        body = mcp_oauth.refresh(d, {"client_id": "c", "client_secret": ""}, "rt-1")
        self.assertIn("access_token", body)
        path, form = [c for c in _StubHandler.calls if c[0] == "/token"][-1]
        self.assertEqual(form["grant_type"], "refresh_token")
        self.assertEqual(form["resource"], self.resource_url)

    def test_dynamic_registration_happens_once(self):
        from safi_app import create_app
        create_app()  # schema, for mcp_oauth_clients
        _StubHandler.register_count = 0
        d = mcp_oauth.discover(self.resource_url)
        key = f"srv_{uuid.uuid4().hex[:8]}"
        first = mcp_oauth.ensure_client(key, {}, d, "https://safi.example/cb")
        again = mcp_oauth.ensure_client(key, {}, d, "https://safi.example/cb")
        self.assertEqual(first["client_id"], "safi-test-client")
        self.assertEqual(again["client_id"], "safi-test-client")
        self.assertEqual(_StubHandler.register_count, 1,
                         "a second login must reuse the stored registration")

    def test_an_empty_env_reference_fails_at_home_not_at_the_idp(self):
        """An unset ${VAR} must be a clear local error, never a redirect to the
        IdP with a blank client_id (GitHub renders that as a bare 404)."""
        d = mcp_oauth.discover(self.resource_url)
        with self.assertRaises(mcp_oauth.OAuthConfigError) as ctx:
            mcp_oauth.ensure_client(
                "x", {"client_id": "${MCP_UNSET_VAR_FOR_TEST}"}, d, "https://x/cb")
        self.assertIn("empty", str(ctx.exception))

    def test_configured_credentials_beat_registration(self):
        d = mcp_oauth.discover(self.resource_url)
        client = mcp_oauth.ensure_client(
            "irrelevant", {"client_id": "operator-set"}, d, "https://x/cb")
        self.assertEqual(client["client_id"], "operator-set")


class BootWithOauthServerTests(unittest.TestCase):
    """start() with an OAuth server in the file must return, not deadlock.

    The regression that reached the demo host: start() held the runtime lock
    and called the public register_offline, which takes it again. Every boot
    with an OAuth server configured hung; resyncs worked because that path had
    already been fixed. The watchdog thread is what makes this test FAIL fast
    instead of hanging the suite if the deadlock ever returns.
    """

    def test_boot_registers_an_oauth_server_and_returns(self):
        from safi_app.core import mcp_runtime

        result = {}

        def boot():
            result["summary"] = mcp_runtime.start({
                "authed": {
                    "transport": "http",
                    "url": "https://tools.example.com/mcp",
                    "auth": "oauth",
                    "cached_tools": [{"name": "cached_tool", "description": "d"}],
                },
            }, reserved_tool_names=frozenset())

        worker = threading.Thread(target=boot, daemon=True)
        worker.start()
        worker.join(timeout=15)
        try:
            self.assertFalse(worker.is_alive(), "start() deadlocked with an OAuth server")
            entry = result["summary"]["servers"]["authed"]
            self.assertEqual(entry["auth"], "oauth")
            self.assertEqual(entry["tools"], ["cached_tool"])
        finally:
            if not worker.is_alive():
                mcp_runtime.shutdown()


class RouteTests(unittest.TestCase):
    """The Flask half: redirect out, validate back, store encrypted."""

    @classmethod
    def setUpClass(cls):
        cls.stub, cls.base = _start_stub()
        cls.resource_url = f"{cls.base}/mcp"

        cls.tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"authsrv": {"transport": "http", "url": cls.resource_url,
                               "auth": "oauth"}}, cls.tmp)
        cls.tmp.close()
        cls.old_env = os.environ.get("MCP_SERVERS_JSON")
        os.environ["MCP_SERVERS_JSON"] = cls.tmp.name

        from safi_app import create_app
        from safi_app.persistence import database as db
        cls.db = db
        cls.app = create_app()
        cls.app.config["TESTING"] = True

        cls.org = str(uuid.uuid4())
        cls.user = f"oauth_{uuid.uuid4().hex[:8]}"
        cls._exec("INSERT INTO organizations (id, name) VALUES (%s, %s)",
                  (cls.org, "OAuth Test Org"))
        # Admin, deliberately: the connect gate lets admins through always
        # (bootstrap: the first sign-in is what discovers the catalog), so the
        # flow tests run as one. Member-facing gating gets its own users below.
        cls._exec("INSERT INTO users (id, email, name, org_id, role) "
                  "VALUES (%s, %s, %s, %s, 'admin')",
                  (cls.user, f"{cls.user}@example.test", "OAuth", cls.org))

    @classmethod
    def tearDownClass(cls):
        cls._exec("DELETE FROM oauth_tokens WHERE user_id=%s", (cls.user,))
        cls._exec("DELETE FROM sessions WHERE user_id=%s", (cls.user,))
        cls._exec("DELETE FROM users WHERE id=%s", (cls.user,))
        cls._exec("DELETE FROM organizations WHERE id=%s", (cls.org,))
        cls.stub.shutdown()
        if cls.old_env is None:
            os.environ.pop("MCP_SERVERS_JSON", None)
        else:
            os.environ["MCP_SERVERS_JSON"] = cls.old_env
        os.unlink(cls.tmp.name)

    @classmethod
    def _exec(cls, sql, params=()):
        conn = cls.db.get_db_connection()
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        cur.close()
        conn.close()

    def _client(self, user=None):
        from support import login
        client = self.app.test_client()
        login(client, user or self.user, self.org)
        return client

    def test_login_redirects_to_the_idp_with_the_full_contract(self):
        mcp_oauth.clear_discovery_cache()
        client = self._client()
        resp = client.get("/api/mcp/auth/authsrv/login")
        self.assertEqual(resp.status_code, 302)
        q = {k: v[0] for k, v in parse_qs(urlparse(resp.location).query).items()}
        self.assertEqual(q["response_type"], "code")
        self.assertEqual(q["code_challenge_method"], "S256")
        self.assertEqual(q["resource"], self.resource_url)
        self.assertTrue(q["state"])

    def test_callback_with_a_wrong_state_stores_nothing(self):
        client = self._client()
        client.get("/api/mcp/auth/authsrv/login")
        resp = client.get("/api/mcp/auth/authsrv/callback?code=good-code&state=forged")
        self.assertEqual(resp.status_code, 400)
        self.assertIsNone(self.db.get_oauth_token(self.user, "mcp:authsrv"))

    def test_the_full_round_trip_stores_an_encrypted_token(self):
        client = self._client()
        client.get("/api/mcp/auth/authsrv/login")
        with client.session_transaction() as sess:
            state = sess["mcp_oauth_pending"]["state"]
        resp = client.get(f"/api/mcp/auth/authsrv/callback?code=good-code&state={state}")
        self.assertEqual(resp.status_code, 302)

        row = self.db.get_oauth_token(self.user, "mcp:authsrv")
        self.assertTrue(row and row["access_token"].startswith("at-authorization_code"))
        # And encrypted at rest: the raw column must not be the plaintext.
        conn = self.db.get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT access_token FROM oauth_tokens WHERE user_id=%s AND provider=%s",
                    (self.user, "mcp:authsrv"))
        raw = cur.fetchone()[0]
        cur.close(); conn.close()
        from safi_app.persistence import crypto
        if crypto.is_enabled():
            self.assertNotEqual(raw, row["access_token"])

    def _member(self):
        member = f"oauth_mem_{uuid.uuid4().hex[:8]}"
        self._exec("INSERT INTO users (id, email, name, org_id, role) "
                   "VALUES (%s, %s, %s, %s, 'member')",
                   (member, f"{member}@example.test", "Member", self.org))
        self.addCleanup(self._exec, "DELETE FROM oauth_tokens WHERE user_id=%s", (member,))
        self.addCleanup(self._exec, "DELETE FROM sessions WHERE user_id=%s", (member,))
        self.addCleanup(self._exec, "DELETE FROM users WHERE id=%s", (member,))
        return member

    def test_a_member_with_no_agent_grant_cannot_connect(self):
        """Connecting is the means to an agent's end. A member none of whose
        agents carry the server's tools gets a refusal that says why, not an
        invitation to grant a token nothing will read."""
        resp = self._client(self._member()).get("/api/mcp/auth/authsrv/login")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("policy", resp.get_json()["error"])

    def test_a_member_whose_agent_is_granted_the_server_can_connect(self):
        import json as _json
        member = self._member()
        agent_key = f"oauth_probe_{uuid.uuid4().hex[:6]}"
        self._exec("""INSERT INTO agents
                      (agent_key, name, org_id, created_by, visibility, tools_json)
                      VALUES (%s,%s,%s,%s,'member',%s)""",
                   (agent_key, "OAuth Probe", self.org, self.user,
                    _json.dumps(["authsrv"])))
        self.addCleanup(self._exec, "DELETE FROM agents WHERE agent_key=%s", (agent_key,))
        from safi_app.core.services import mcp_oauth
        mcp_oauth.clear_discovery_cache()
        resp = self._client(member).get("/api/mcp/auth/authsrv/login")
        self.assertEqual(resp.status_code, 302)

    def test_auth_status_reports_the_server_with_both_flags(self):
        body = self._client(self._member()).get("/api/auth/status").get_json()
        servers = {s["key"]: s for s in body.get("mcp_servers", [])}
        self.assertIn("authsrv", servers)
        self.assertTrue(servers["authsrv"]["allowed"])
        self.assertFalse(servers["authsrv"]["usable"],
                         "no agent grants it, so it must not be offered")
        self.assertIn("login", servers["authsrv"])

    def test_a_guest_is_refused_at_login_and_callback(self):
        guest = f"demo_{uuid.uuid4()}"
        self._exec("INSERT INTO users (id, email, name, org_id, role) "
                   "VALUES (%s, %s, %s, %s, 'admin')",
                   (guest, f"{guest}@demo.local", "Guest", self.org))
        try:
            client = self._client(guest)
            self.assertEqual(client.get("/api/mcp/auth/authsrv/login").status_code, 403)
            self.assertEqual(
                client.get("/api/mcp/auth/authsrv/callback?code=x&state=y").status_code, 403)
        finally:
            self._exec("DELETE FROM sessions WHERE user_id=%s", (guest,))
            self._exec("DELETE FROM users WHERE id=%s", (guest,))

    def test_an_unknown_server_is_a_404(self):
        self.assertEqual(
            self._client().get("/api/mcp/auth/nonesuch/login").status_code, 404)


class LiveProtectedServerTests(unittest.TestCase):
    """A real MCP server that demands a Bearer token, spoken to per user."""

    GOOD = "the-audience-bound-token"

    @classmethod
    def setUpClass(cls):
        import asyncio
        import uvicorn
        from mcp.server import MCPServer

        server = MCPServer(name="protected")

        @server.tool()
        def secure_echo(message: str) -> str:
            """Echo, behind authorization."""
            return f"secure: {message}"

        inner = server.streamable_http_app()

        async def gated(scope, receive, send):
            # The reference middleware's contract, minimally: a Bearer token or
            # a 401. Audience validation is the resource server's job and is
            # covered by the TypeScript reference; what SAFi's client side owes
            # is presenting the token, which is exactly what this asserts.
            if scope["type"] == "http":
                headers = {k.decode(): v.decode() for k, v in scope.get("headers", [])}
                if headers.get("authorization") != f"Bearer {cls.GOOD}":
                    await send({"type": "http.response.start", "status": 401,
                                "headers": [(b"content-type", b"application/json")]})
                    await send({"type": "http.response.body",
                                "body": b'{"error":"unauthorized"}'})
                    return
            await inner(scope, receive, send)

        config = uvicorn.Config(gated, host="127.0.0.1", port=0, log_level="error")
        cls.uv = uvicorn.Server(config)
        cls.thread = threading.Thread(target=cls.uv.run, daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.uv.started:
                break
            time.sleep(0.1)
        port = cls.uv.servers[0].sockets[0].getsockname()[1]
        cls.url = f"http://127.0.0.1:{port}/mcp"

    @classmethod
    def tearDownClass(cls):
        cls.uv.should_exit = True
        cls.thread.join(timeout=10)

    def test_a_call_with_the_token_executes_as_that_user(self):
        import asyncio
        from safi_app.core import mcp_runtime
        out = asyncio.run(mcp_runtime.call_with_token(
            self.url, "secure_echo", {"message": "per-user"}, self.GOOD))
        self.assertIn("secure: per-user", out)

    def test_a_bad_token_reads_as_reconnect_not_a_traceback(self):
        import asyncio
        from safi_app.core import mcp_runtime
        out = asyncio.run(mcp_runtime.call_with_token(
            self.url, "secure_echo", {"message": "x"}, "stolen-or-expired"))
        self.assertTrue(out.startswith("ERROR:"))
        self.assertNotIn("Traceback", out)
        self.assertIn("refused", out)

    def test_discovery_with_the_token_lists_the_tools(self):
        import asyncio
        from safi_app.core import mcp_runtime
        tools = asyncio.run(mcp_runtime.list_tools_with_token(self.url, self.GOOD))
        self.assertEqual([t["name"] for t in tools], ["secure_echo"])
        self.assertEqual(tools[0]["input_schema"]["type"], "object")


class ReferenceServerTests(unittest.TestCase):
    """The Python reference resource server, driven with real signed JWTs.

    This is the confused-deputy test in executable form: a token whose `aud`
    is some OTHER service is refused even though the signature, issuer and
    expiry are all valid. The TypeScript version of this reference compiled
    and was never executed by CI; being Python is what lets the same suite
    that tests the client also prove the server half.
    """

    @classmethod
    def setUpClass(cls):
        from authlib.jose import JsonWebKey, jwt as make_jwt
        import uvicorn
        import importlib.util

        # A real signing key, its public half served as the stub IdP's JWKS.
        cls.key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
        public = cls.key.as_dict(is_private=False)
        public["kid"] = "test-key"
        _StubHandler.jwks = {"keys": [public]}
        cls.idp, cls.idp_base = _start_stub()

        spec = importlib.util.spec_from_file_location(
            "reference_server",
            Path(__file__).resolve().parent.parent / "scripts" / "oauth_resource_server.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Bind the app first so RESOURCE_URI can carry the real port.
        import socket
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        cls.resource_uri = f"http://127.0.0.1:{port}/mcp"
        app = module.build_app(cls.resource_uri, cls.idp_base, f"{cls.idp_base}/jwks")

        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        cls.uv = uvicorn.Server(config)
        cls.thread = threading.Thread(target=cls.uv.run, daemon=True)
        cls.thread.start()
        for _ in range(100):
            if cls.uv.started:
                break
            time.sleep(0.1)

        def mint(aud, exp_offset=3600, sub="member-42"):
            return make_jwt.encode(
                {"alg": "RS256", "kid": "test-key"},
                {"iss": cls.idp_base, "aud": aud, "sub": sub,
                 "exp": int(time.time()) + exp_offset, "scope": "tools.read"},
                cls.key).decode()
        cls.mint = staticmethod(mint)

    @classmethod
    def tearDownClass(cls):
        cls.uv.should_exit = True
        cls.thread.join(timeout=10)
        cls.idp.shutdown()

    def test_prm_is_served_without_authentication(self):
        import requests
        resp = requests.get(
            self.resource_uri.replace("/mcp", "/.well-known/oauth-protected-resource"),
            timeout=5)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["authorization_servers"], [self.idp_base])

    def test_no_token_gets_a_401_that_points_at_the_metadata(self):
        import requests
        resp = requests.post(self.resource_uri, json={}, timeout=5)
        self.assertEqual(resp.status_code, 401)
        self.assertIn("resource_metadata=", resp.headers.get("WWW-Authenticate", ""))

    def test_a_correctly_bound_token_executes_as_its_subject(self):
        import asyncio
        from safi_app.core import mcp_runtime
        token = self.mint(aud=self.resource_uri)
        out = asyncio.run(mcp_runtime.call_with_token(
            self.resource_uri, "whoami", {}, token))
        self.assertIn("member-42", out)

    def test_the_confused_deputy_is_refused(self):
        """Valid signature, valid issuer, valid expiry, WRONG audience: a token
        minted for some other service must not open this one."""
        import asyncio
        from safi_app.core import mcp_runtime
        token = self.mint(aud="https://some-other-service.example/api")
        out = asyncio.run(mcp_runtime.call_with_token(
            self.resource_uri, "whoami", {}, token))
        self.assertTrue(out.startswith("ERROR:"))
        self.assertIn("refused", out)

    def test_an_expired_token_is_refused(self):
        import asyncio
        from safi_app.core import mcp_runtime
        token = self.mint(aud=self.resource_uri, exp_offset=-60)
        out = asyncio.run(mcp_runtime.call_with_token(
            self.resource_uri, "whoami", {}, token))
        self.assertTrue(out.startswith("ERROR:"))

    def test_a_garbage_token_is_refused_not_crashed(self):
        import asyncio
        from safi_app.core import mcp_runtime
        out = asyncio.run(mcp_runtime.call_with_token(
            self.resource_uri, "whoami", {}, "not-a-jwt-at-all"))
        self.assertTrue(out.startswith("ERROR:"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
