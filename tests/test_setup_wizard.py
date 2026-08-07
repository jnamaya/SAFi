"""
The setup wizard writes .env by substituting values into .env.example, so the
template is the single source of truth. These tests defend that arrangement.

The load-bearing ones:

  * test_every_written_key_exists_in_template — the drift guard. A wizard that
    writes a key the template does not define would silently drop it from the
    generated .env, producing a config that boots with a missing secret.
  * test_generated_env_satisfies_production_validate — renders a production
    answer set and runs the real Config.validate() against it. This is what
    stops the wizard shipping a .env that fails on first `docker compose up`.
  * test_fernet_key_is_accepted_by_fernet — the wizard reproduces
    Fernet.generate_key() from the standard library, because it must run before
    requirements.txt is installed. If the upstream key format ever changes, this
    fails instead of the encryption layer failing in production.

Run:  venv/bin/python tests/test_setup_wizard.py
"""
import importlib.util
import os
import sys
import unittest
import urllib.error
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# scripts/ is not a package; load setup.py by path.
_spec = importlib.util.spec_from_file_location("safi_setup", REPO_ROOT / "scripts" / "setup.py")
setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup)


def render_from(values):
    lines, index = setup.parse_template(setup.TEMPLATE)
    return setup.render(lines, index, values)


def parse_env(text):
    out = {}
    for line in text.splitlines():
        m = setup.ASSIGNMENT.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


class TemplateContract(unittest.TestCase):
    """The wizard and .env.example must not drift apart."""

    def setUp(self):
        self.lines, self.index = setup.parse_template(setup.TEMPLATE)

    def test_every_written_key_exists_in_template(self):
        written = set(setup.generated_secrets())
        written |= {
            "FLASK_ENV", "SAFI_DEPLOYMENT_MODE", "APP_PORT", "WEB_BASE_URL",
            "ALLOWED_ORIGINS", "SESSION_COOKIE_SECURE",
            "SAFI_LOCAL_ADMIN_EMAIL", "SAFI_LOCAL_ADMIN_PASSWORD",
            "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
            "MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET",
        }
        written |= {p["key"] for p in setup.PROVIDERS}
        missing = sorted(written - set(self.index))
        self.assertEqual([], missing,
                         f"wizard writes keys absent from .env.example: {missing}")

    def test_commented_examples_are_not_settable(self):
        """
        The template ships #SAFI_INTELLECT_MODEL=... as documentation. Treating a
        commented line as an assignment would uncomment it and pin a model the
        user never chose.
        """
        self.assertNotIn("SAFI_INTELLECT_MODEL", self.index)
        self.assertNotIn("SAFI_BUILTIN_AGENTS", self.index)

    def test_provider_keys_are_the_ones_config_checks(self):
        """
        Config.validate() requires one of a specific list of provider keys. If a
        provider is added there and not here, the wizard can produce a .env that
        fails the "no LLM API key configured" check.
        """
        source = (REPO_ROOT / "safi_app" / "config.py").read_text(encoding="utf-8")
        start = source.index("llm_keys = [")
        block = source[start:source.index("]", start)]
        in_config = {f"{n}_API_KEY" for n in
                     ("GROQ", "OPENAI", "ANTHROPIC", "GEMINI", "MISTRAL",
                      "DEEPSEEK", "ZHIPU", "CEREBRAS")
                     if f"cls.{n}_API_KEY" in block}
        self.assertEqual(in_config, {p["key"] for p in setup.PROVIDERS})

    def test_render_preserves_comments_and_line_count(self):
        out = render_from({"APP_PORT": "5050"})
        self.assertEqual(len(self.lines), len(out.splitlines()))
        self.assertIn("# ── Database ─", out)
        self.assertIn("APP_PORT=5050", out)

    def test_render_rejects_unknown_key(self):
        with self.assertRaises(SystemExit):
            render_from({"NOT_A_REAL_SAFI_VARIABLE": "x"})


class GeneratedSecrets(unittest.TestCase):

    def test_no_placeholder_survives(self):
        """Every change-me-* literal in the template must be replaced."""
        values = setup.generated_secrets()
        values["SAFI_LOCAL_ADMIN_PASSWORD"] = setup.gen_password()
        values["GROQ_API_KEY"] = "gsk_test"
        env = parse_env(render_from(values))
        placeholders = {k: v for k, v in env.items() if "change-me" in v}
        self.assertEqual({}, placeholders,
                         f"placeholder values left in generated .env: {placeholders}")

    def test_secrets_are_unique_per_run(self):
        a, b = setup.generated_secrets(), setup.generated_secrets()
        for key in a:
            self.assertNotEqual(a[key], b[key], f"{key} repeated across runs")

    def test_fernet_key_is_accepted_by_fernet(self):
        from cryptography.fernet import Fernet
        key = setup.gen_fernet_key()
        token = Fernet(key).encrypt(b"governed turn")
        self.assertEqual(b"governed turn", Fernet(key).decrypt(token))

    def test_passwords_need_no_url_escaping(self):
        """A password with / or + breaks a MySQL connection string."""
        import string
        allowed = set(string.ascii_letters + string.digits + "-_")
        for _ in range(50):
            self.assertTrue(set(setup.gen_password()) <= allowed)


class ValidateAgainstRealConfig(unittest.TestCase):
    """
    Load the generated values into the real Config and run its validator. This
    is the check that the wizard's output actually boots.
    """

    def _validate(self, env):
        """
        Import Config fresh with `env` as the whole environment, and validate.

        config.py:9 calls load_dotenv(dotenv_path=<repo>/.env, override=True),
        so on any developer machine the real .env would beat the values set
        here — the same hazard docker-compose.test.yml avoids by refusing to
        mount the repo root. Neutralising the loader makes this test give the
        same answer everywhere, with or without a .env on disk.
        """
        import dotenv
        for mod in [m for m in sys.modules if m.startswith("safi_app")]:
            del sys.modules[mod]
        saved_env = dict(os.environ)
        saved_loader = dotenv.load_dotenv
        # Keep the process usable; drop everything that could configure SAFi.
        keep = {k: saved_env[k] for k in ("PATH", "HOME", "LANG", "PYTHONPATH")
                if k in saved_env}
        try:
            dotenv.load_dotenv = lambda *a, **k: False
            os.environ.clear()
            os.environ.update(keep)
            os.environ.update(env)
            from safi_app.config import Config
            Config.validate()
        finally:
            dotenv.load_dotenv = saved_loader
            os.environ.clear()
            os.environ.update(saved_env)

    def test_generated_env_satisfies_production_validate(self):
        values = setup.generated_secrets()
        values.update({
            "FLASK_ENV": "production",
            "SAFI_DEPLOYMENT_MODE": "production",
            "WEB_BASE_URL": "https://safi.example.org",
            "SAFI_LOCAL_ADMIN_EMAIL": "admin@example.org",
            "SAFI_LOCAL_ADMIN_PASSWORD": setup.gen_password(),
            "GROQ_API_KEY": "gsk_test",
        })
        self._validate(parse_env(render_from(values)))  # raises if invalid

    def test_trial_env_satisfies_validate(self):
        values = setup.generated_secrets()
        values.update({
            "FLASK_ENV": "development",
            "SAFI_DEPLOYMENT_MODE": "trial",
            "SAFI_LOCAL_ADMIN_EMAIL": "admin@localhost",
            "SAFI_LOCAL_ADMIN_PASSWORD": setup.gen_password(),
            "GROQ_API_KEY": "gsk_test",
        })
        self._validate(parse_env(render_from(values)))

    def test_missing_provider_key_still_fails(self):
        """Guard against the previous test passing for the wrong reason."""
        values = setup.generated_secrets()
        values.update({
            "FLASK_ENV": "development",
            "SAFI_LOCAL_ADMIN_EMAIL": "admin@localhost",
            "SAFI_LOCAL_ADMIN_PASSWORD": setup.gen_password(),
        })
        env = parse_env(render_from(values))
        env = {k: v for k, v in env.items() if not k.endswith("_API_KEY")}
        with self.assertRaises(ValueError):
            self._validate(env)


class KeyVerification(unittest.TestCase):
    """
    Offline tests for the provider check. The regression they exist for: the
    first version sent urllib's default User-Agent, Cloudflare answered 403
    ("error code: 1010") before Groq ever looked at the key, and the wizard
    reported every key — including working ones — as rejected.
    """

    def _capture(self, raises=None, status=200):
        """Run verify_key against a stub, returning (result, captured Request)."""
        import urllib.request
        captured = {}

        class _Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            captured["req"] = req
            if raises:
                raise raises
            resp = _Resp()
            resp.status = status
            return resp

        real = urllib.request.urlopen
        setup.urllib.request.urlopen = fake_urlopen
        try:
            groq = next(p for p in setup.PROVIDERS if p["key"] == "GROQ_API_KEY")
            return setup.verify_key(groq, "gsk_test_key"), captured.get("req")
        finally:
            setup.urllib.request.urlopen = real

    def _http_error(self, code):
        import urllib.error
        return urllib.error.HTTPError("https://example", code, "err", {}, None)

    def test_every_request_carries_a_user_agent(self):
        """The root cause. Without this header the check is worthless."""
        _, req = self._capture()
        self.assertIn("User-agent", req.headers,
                      f"no User-Agent sent; headers were {req.headers}")
        self.assertTrue(req.headers["User-agent"].startswith("SAFi-setup/"))

    def test_user_agent_does_not_displace_the_auth_header(self):
        _, req = self._capture()
        self.assertEqual("Bearer gsk_test_key", req.headers["Authorization"])

    def test_403_is_not_a_rejection(self):
        """
        403 is what a WAF returns for bot heuristics, a datacentre IP or a geo
        rule — none of which say anything about the key. Only 401 does.
        """
        (ok, msg), _ = self._capture(raises=self._http_error(403))
        self.assertTrue(ok, "403 must not be reported as an invalid key")
        self.assertIn("could not check", msg)

    def test_401_is_a_rejection(self):
        (ok, msg), _ = self._capture(raises=self._http_error(401))
        self.assertFalse(ok)
        self.assertIn("not valid", msg)

    def test_network_failure_is_never_fatal(self):
        """Offline and behind-a-proxy installs must still complete."""
        import urllib.error
        for err in (urllib.error.URLError("no route"), TimeoutError(), OSError()):
            (ok, _), _ = self._capture(raises=err)
            self.assertTrue(ok, f"{type(err).__name__} must not reject the key")

    def test_success_is_reported_as_accepted(self):
        (ok, msg), _ = self._capture(status=200)
        self.assertTrue(ok)
        self.assertIn("accepted", msg)

    def test_gemini_sends_the_key_in_the_query_string(self):
        """Gemini takes ?key=, not a bearer header — a wrong shape reads as 403/401."""
        import urllib.request
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["req"] = req
            raise urllib.error.URLError("stop here")

        real = urllib.request.urlopen
        setup.urllib.request.urlopen = fake_urlopen
        try:
            gem = next(p for p in setup.PROVIDERS if p["key"] == "GEMINI_API_KEY")
            setup.verify_key(gem, "AIza-test")
        finally:
            setup.urllib.request.urlopen = real
        self.assertIn("key=AIza-test", captured["req"].full_url)
        self.assertNotIn("Authorization", captured["req"].headers)

    def test_provider_without_an_endpoint_is_accepted_unchecked(self):
        zhipu = next(p for p in setup.PROVIDERS if p["key"] == "ZHIPU_API_KEY")
        ok, msg = setup.verify_key(zhipu, "anything")
        self.assertTrue(ok)
        self.assertIn("not checked", msg)


class BackupNaming(unittest.TestCase):

    def test_backup_never_overwrites_an_existing_backup(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / ".env"
            target.write_text("first")
            first = setup.backup_path(target)
            self.assertEqual(".env.bak", first.name)
            first.write_text("saved")
            second = setup.backup_path(target)
            self.assertNotEqual(first, second)
            self.assertFalse(second.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
