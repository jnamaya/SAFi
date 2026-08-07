#!/usr/bin/env python3
"""
Interactive setup wizard — writes a working .env so nobody has to hand-edit a
57-variable template to answer three questions.

    python scripts/setup.py              # interactive
    python scripts/setup.py --defaults   # non-interactive (CI / scripted installs)
    python scripts/setup.py --force      # overwrite an existing .env (backed up first)

WHY THIS IS A CLI SCRIPT AND NOT A PAGE IN THE APP
--------------------------------------------------
docker-compose.yml interpolates DB_USER, DB_PASSWORD, DB_NAME,
MYSQL_ROOT_PASSWORD and APP_PORT *before either container exists*. Those values
have to be on disk in .env before anything can serve a page, so a browser-based
first-run wizard is structurally impossible for exactly the variables that
matter most. .env remains the artifact; this is a generator for it.

WHY IT ONLY IMPORTS THE STANDARD LIBRARY
----------------------------------------
It runs on the host, before `docker compose up`, in whatever Python happens to
be installed. It cannot assume requirements.txt has ever been installed — so no
`requests`, and no `cryptography` (see gen_fernet_key for how the encryption key
is produced without it).

WHY IT REWRITES THE TEMPLATE INSTEAD OF PRINTING KEY=VALUE LINES
----------------------------------------------------------------
The output is .env.example with values substituted in place, comments and all.
That keeps one source of truth: a variable added to the template flows through
here for free, the generated .env stays self-documenting, and
test_setup_wizard.py asserts every key this writes still exists upstream.
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import secrets
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / ".env.example"
TARGET = REPO_ROOT / ".env"

VERIFY_TIMEOUT = 8  # seconds — a slow provider must not hang the install

# Providers in the order they are offered. `verify` is (url, headers-builder);
# None means the provider has no stable, cheap listing endpoint to check against,
# so the key is accepted without a round trip rather than guessed at.
PROVIDERS: List[dict] = [
    {
        "key": "GROQ_API_KEY", "name": "Groq",
        "note": "free tier, fast — easiest place to start",
        "signup": "https://console.groq.com",
        "verify": ("https://api.groq.com/openai/v1/models",
                   lambda k: {"Authorization": f"Bearer {k}"}),
    },
    {
        "key": "GEMINI_API_KEY", "name": "Google Gemini",
        "note": "free tier",
        "signup": "https://aistudio.google.com",
        "verify": ("https://generativelanguage.googleapis.com/v1beta/models",
                   None),  # key goes in the query string; handled in verify_key
    },
    {
        "key": "OPENAI_API_KEY", "name": "OpenAI",
        "note": "paid",
        "signup": "https://platform.openai.com",
        "verify": ("https://api.openai.com/v1/models",
                   lambda k: {"Authorization": f"Bearer {k}"}),
    },
    {
        "key": "ANTHROPIC_API_KEY", "name": "Anthropic",
        "note": "paid",
        "signup": "https://console.anthropic.com",
        "verify": ("https://api.anthropic.com/v1/models",
                   lambda k: {"x-api-key": k, "anthropic-version": "2023-06-01"}),
    },
    {
        "key": "DEEPSEEK_API_KEY", "name": "DeepSeek",
        "note": "paid, inexpensive",
        "signup": "https://platform.deepseek.com",
        "verify": ("https://api.deepseek.com/models",
                   lambda k: {"Authorization": f"Bearer {k}"}),
    },
    {
        "key": "MISTRAL_API_KEY", "name": "Mistral",
        "note": "paid",
        "signup": "https://console.mistral.ai",
        "verify": ("https://api.mistral.ai/v1/models",
                   lambda k: {"Authorization": f"Bearer {k}"}),
    },
    {
        "key": "CEREBRAS_API_KEY", "name": "Cerebras",
        "note": "paid",
        "signup": "https://cloud.cerebras.ai",
        "verify": ("https://api.cerebras.ai/v1/models",
                   lambda k: {"Authorization": f"Bearer {k}"}),
    },
    {
        "key": "ZHIPU_API_KEY", "name": "Zhipu / GLM",
        "note": "paid",
        "signup": "https://open.bigmodel.cn",
        "verify": None,
    },
]


# ── terminal helpers ─────────────────────────────────────────────────────────

def _c(code: str, s: str) -> str:
    """Colour only when stdout is a real terminal, so piped output stays clean."""
    return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() else s


bold = lambda s: _c("1", s)
dim = lambda s: _c("2", s)
green = lambda s: _c("32", s)
yellow = lambda s: _c("33", s)
red = lambda s: _c("31", s)


def heading(n: int, total: int, text: str) -> None:
    print(f"\n{bold(f'[{n}/{total}] {text}')}")
    print(dim("─" * (len(text) + 8)))


def _read(prompt: str) -> str:
    """
    Single entry point for every prompt, so a closed stdin produces one clear
    message instead of a traceback from whichever question came first.
    """
    try:
        return input(prompt).strip()
    except EOFError:
        raise SystemExit(red(
            "\n\nAborted — stdin closed with the wizard still asking questions.\n"
            "Run it in a terminal, or use --defaults for a non-interactive install.\n"))


def ask(prompt: str, default: str = "", secret_hint: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        raw = _read(f"  {prompt}{dim(suffix)}: ")
        if raw:
            return raw
        if default:
            return default
        if secret_hint:
            print(red("  A value is required here."))
        else:
            print(red("  Please enter a value."))


def ask_choice(prompt: str, options: List[Tuple[str, str, str]], default: int = 0) -> str:
    """options: (value, label, help). Returns the chosen value."""
    print(f"  {prompt}")
    for i, (_, label, help_text) in enumerate(options, 1):
        marker = dim(" (default)") if i - 1 == default else ""
        print(f"    {bold(str(i))}. {label}{marker}")
        if help_text:
            print(f"       {dim(help_text)}")
    while True:
        raw = _read(f"  Choose 1–{len(options)} {dim(f'[{default + 1}]')}: ")
        if not raw:
            return options[default][0]
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        print(red(f"  Enter a number between 1 and {len(options)}."))


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = _read(f"  {prompt} {dim(f'[{suffix}]')}: ").lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print(red("  Answer y or n."))


# ── secret generation ────────────────────────────────────────────────────────

def gen_secret() -> str:
    return secrets.token_hex(32)


def gen_password() -> str:
    """URL-safe so it survives a MySQL connection string without escaping."""
    return secrets.token_urlsafe(24)


def gen_fernet_key() -> str:
    """
    A Fernet key is exactly urlsafe_b64encode(32 random bytes) — which is what
    cryptography.fernet.Fernet.generate_key() returns. Reproducing it from the
    standard library keeps this script runnable before requirements.txt is
    installed. Verified against Fernet(key) in tests/test_setup_wizard.py, so
    this stays honest if the upstream format ever changes.
    """
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


# ── template parsing ─────────────────────────────────────────────────────────

ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def parse_template(path: Path) -> Tuple[List[str], Dict[str, int]]:
    """
    Returns the template's lines and a map of KEY -> line index.

    Only uncommented assignments at the start of a line count. The template
    deliberately ships commented-out examples (#SAFI_INTELLECT_MODEL=...) that
    exist to be read, not set; treating those as settable would uncomment them
    and pin models the user never chose.
    """
    if not path.exists():
        raise SystemExit(red(f"Cannot find {path} — run this from a full checkout."))
    lines = path.read_text(encoding="utf-8").splitlines()
    index: Dict[str, int] = {}
    for i, line in enumerate(lines):
        m = ASSIGNMENT.match(line)
        if m:
            index[m.group(1)] = i
    return lines, index


def render(lines: List[str], index: Dict[str, int], values: Dict[str, str]) -> str:
    """Substitute values into the template in place, keeping every comment."""
    out = list(lines)
    unknown = [k for k in values if k not in index]
    if unknown:
        # A key we write that the template does not define would silently vanish
        # from the generated .env. Fail loudly instead.
        raise SystemExit(red(
            "Internal error: these keys are not defined in .env.example: "
            + ", ".join(sorted(unknown))))
    for key, value in values.items():
        out[index[key]] = f"{key}={value}"
    return "\n".join(out) + "\n"


# ── environment checks ───────────────────────────────────────────────────────

def port_is_free(port: int) -> bool:
    """Best-effort: a port already bound would make `docker compose up` fail late."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def verify_key(provider: dict, key: str) -> Tuple[bool, str]:
    """
    Best-effort liveness check. Returns (ok, message). A network failure is
    never fatal — plenty of people set up behind a proxy or offline and paste a
    key they know is good.
    """
    if not provider.get("verify"):
        return True, "not checked (provider has no listing endpoint)"
    url, headers_fn = provider["verify"]
    headers = headers_fn(key) if headers_fn else {}
    if provider["key"] == "GEMINI_API_KEY":
        url = f"{url}?key={urllib.parse.quote(key)}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=VERIFY_TIMEOUT) as resp:
            if 200 <= resp.status < 300:
                return True, "key accepted by the provider"
            return True, f"unexpected status {resp.status} — accepting anyway"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False, f"provider rejected the key (HTTP {e.code})"
        return True, f"could not check (HTTP {e.code}) — accepting"
    except Exception as e:  # DNS, TLS, proxy, timeout, offline
        return True, f"could not reach the provider ({type(e).__name__}) — accepting"


# ── the wizard ───────────────────────────────────────────────────────────────

def collect_interactive() -> Dict[str, str]:
    values: Dict[str, str] = {}
    total = 4

    # ── 1. What is this instance? ────────────────────────────────────────────
    # FLASK_ENV and SAFI_DEPLOYMENT_MODE both take the word "production" and mean
    # different things (strictness vs audience). Asking once in plain language and
    # setting both is the single biggest reason this wizard exists.
    heading(1, total, "What is this instance for?")
    kind = ask_choice("This sets both the startup strictness and the audience.", [
        ("trial", "Trying SAFi out locally",
         "Relaxed startup checks, demo login on. Nothing is exposed to the internet."),
        ("production", "A real deployment other people will use",
         "Strict startup checks: a login method, an encryption key and a public URL."),
        ("showcase", "A public demo instance",
         "Strict checks, plus framing that names the running model."),
    ], default=0)

    is_prod = kind in ("production", "showcase")
    values["FLASK_ENV"] = "production" if is_prod else "development"
    values["SAFI_DEPLOYMENT_MODE"] = kind

    # ── 2. LLM provider ──────────────────────────────────────────────────────
    heading(2, total, "AI provider")
    print(dim("  SAFi needs at least one model provider. You can add more later\n"
              "  by filling in the other *_API_KEY lines in .env."))
    print()
    chosen = ask_choice("Which provider do you want to start with?", [
        (p["key"], f"{p['name']} {dim('— ' + p['note'])}", p["signup"])
        for p in PROVIDERS
    ], default=0)
    provider = next(p for p in PROVIDERS if p["key"] == chosen)

    while True:
        api_key = ask(f"Paste your {provider['name']} API key", secret_hint=True)
        print(dim(f"  Checking the key against {provider['name']}…"))
        ok, msg = verify_key(provider, api_key)
        if ok:
            print(green(f"  ✓ {msg}"))
            break
        print(red(f"  ✗ {msg}"))
        if not ask_yes_no("Try a different key?", default=True):
            print(yellow("  Continuing with the key as entered — SAFi will fail "
                         "at the first model call if it is wrong."))
            break
    values[provider["key"]] = api_key

    # ── 3. Where it will be reachable ────────────────────────────────────────
    heading(3, total, "Network")
    port = 5000
    if not port_is_free(port):
        print(yellow(f"  Port {port} is already in use on this machine."))
        for candidate in range(5001, 5010):
            if port_is_free(candidate):
                port = int(ask("Use which port instead?", str(candidate)))
                break
    else:
        port = int(ask("Port to expose SAFi on", "5000"))
    values["APP_PORT"] = str(port)

    default_url = f"http://localhost:{port}"
    if is_prod:
        print(dim("\n  The public URL matters: OAuth callbacks and CORS are built\n"
                  "  from it, and a wrong value breaks login with no obvious cause."))
        base_url = ask("Public URL where SAFi will be reachable", default_url)
    elif ask_yes_no(f"\n  Will you open SAFi from another machine on your network?",
                    default=False):
        base_url = ask("Address you will browse to (e.g. http://192.168.1.50:%d)" % port,
                       default_url)
    else:
        base_url = default_url

    values["WEB_BASE_URL"] = base_url
    values["ALLOWED_ORIGINS"] = base_url
    # Secure cookies over plain HTTP are simply never sent, which presents as
    # "login does nothing" — derive it from the scheme rather than asking.
    values["SESSION_COOKIE_SECURE"] = "True" if base_url.startswith("https://") else "False"

    # ── 4. Login ─────────────────────────────────────────────────────────────
    heading(4, total, "Login")
    if is_prod:
        print(dim("  Production needs at least one way in. A local admin account\n"
                  "  is the fastest; OAuth can be added to .env at any time."))
        print()
        login = ask_choice("How will people sign in?", [
            ("local", "A local admin account", "No OAuth app to register. You can add OAuth later."),
            ("google", "Google Sign-In", "Needs a client ID and secret from Google Cloud."),
            ("microsoft", "Microsoft / Entra", "Needs an app registration in Azure."),
        ], default=0)
    else:
        login = "local"
        print(dim("  A local admin account will be created so you can sign in\n"
                  "  without registering an OAuth application."))

    admin_email = ask("Admin email address", "admin@localhost")
    admin_password = gen_password()
    values["SAFI_LOCAL_ADMIN_EMAIL"] = admin_email
    values["SAFI_LOCAL_ADMIN_PASSWORD"] = admin_password

    if login == "google":
        print(dim(f"\n  Authorized redirect URI: {base_url}/api/callback/google"))
        values["GOOGLE_CLIENT_ID"] = ask("Google client ID")
        values["GOOGLE_CLIENT_SECRET"] = ask("Google client secret")
    elif login == "microsoft":
        print(dim(f"\n  Redirect URI: {base_url}/api/callback/microsoft"))
        values["MICROSOFT_CLIENT_ID"] = ask("Microsoft client ID")
        values["MICROSOFT_CLIENT_SECRET"] = ask("Microsoft client secret")

    values.update(generated_secrets())
    values["_admin_password"] = admin_password  # stripped before render; shown at the end
    return values


def generated_secrets() -> Dict[str, str]:
    """
    Never prompted for. A human inventing a session secret produces a worse one
    than os.urandom, and a template that ships `change-me-*` placeholders is the
    mechanism by which those placeholders reach production — Config.validate()
    already carries a check for exactly that (safi_app/config.py:461).
    """
    return {
        "FLASK_SECRET_KEY": gen_secret(),
        "SAFI_ENCRYPTION_KEY": gen_fernet_key(),
        "DB_PASSWORD": gen_password(),
        "MYSQL_ROOT_PASSWORD": gen_password(),
        "SAFI_BOT_API_SECRET": gen_secret(),
    }


def collect_defaults() -> Dict[str, str]:
    """
    Non-interactive path for CI and scripted installs. Everything is generated
    except the provider key, which is read from the real environment — the one
    value no script can invent.
    """
    values: Dict[str, str] = {
        "FLASK_ENV": "development",
        "SAFI_DEPLOYMENT_MODE": "trial",
        "APP_PORT": "5000",
        "WEB_BASE_URL": "http://localhost:5000",
        "ALLOWED_ORIGINS": "http://localhost:5000",
        "SESSION_COOKIE_SECURE": "False",
        "SAFI_LOCAL_ADMIN_EMAIL": "admin@localhost",
    }
    found = [p for p in PROVIDERS if os.environ.get(p["key"])]
    if not found:
        raise SystemExit(red(
            "--defaults needs a provider key in the environment. Export one first, e.g.:\n"
            "  export GROQ_API_KEY=gsk_...\n"
            "Accepted: " + ", ".join(p["key"] for p in PROVIDERS)))
    for p in found:
        values[p["key"]] = os.environ[p["key"]]
    values.update(generated_secrets())
    admin_password = gen_password()
    values["SAFI_LOCAL_ADMIN_PASSWORD"] = admin_password
    values["_admin_password"] = admin_password
    print(f"Using {', '.join(p['name'] for p in found)} from the environment.")
    return values


# ── writing ──────────────────────────────────────────────────────────────────

def backup_path(target: Path) -> Path:
    """Never overwrite an existing backup — find the first free name."""
    candidate = target.with_suffix(target.suffix + ".bak")
    n = 1
    while candidate.exists():
        candidate = target.with_name(f"{target.name}.bak.{n}")
        n += 1
    return candidate


def write_env(content: str, force: bool) -> None:
    if TARGET.exists():
        if not force:
            raise SystemExit(red(
                f"{TARGET} already exists.\n"
                "Re-run with --force to replace it (the current file is backed up first)."))
        backup = backup_path(TARGET)
        backup.write_text(TARGET.read_text(encoding="utf-8"), encoding="utf-8")
        print(yellow(f"  Existing .env backed up to {backup.name}"))
    TARGET.write_text(content, encoding="utf-8")
    # It holds a database password, a session secret and an encryption key.
    os.chmod(TARGET, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a working .env for SAFi.")
    parser.add_argument("--defaults", action="store_true",
                        help="non-interactive; provider key comes from the environment")
    parser.add_argument("--force", action="store_true",
                        help="replace an existing .env (backed up first)")
    args = parser.parse_args()

    print(bold("\n  SAFi setup"))
    print(dim("  Writes .env. Nothing else on your system is touched.\n"))

    lines, index = parse_template(TEMPLATE)
    values = collect_defaults() if args.defaults else collect_interactive()
    admin_password = values.pop("_admin_password", "")

    content = render(lines, index, values)
    write_env(content, args.force)

    print(f"\n{green('  ✓ Wrote .env')} {dim('(mode 600)')}")
    print(dim("    Secrets generated: session key, encryption key, database "
              "passwords, admin password."))

    print(bold("\n  Sign in with:"))
    print(f"    email    {values['SAFI_LOCAL_ADMIN_EMAIL']}")
    print(f"    password {bold(admin_password)}")
    print(yellow("    Shown once. It is in .env as SAFI_LOCAL_ADMIN_PASSWORD."))

    if values.get("SAFI_ENCRYPTION_KEY"):
        print(yellow("\n  Back up SAFI_ENCRYPTION_KEY somewhere off this machine."
                     "\n  Losing it makes every encrypted record permanently unreadable."))

    print(bold("\n  Next:"))
    print("    docker compose up")
    print(f"    then open {values['WEB_BASE_URL']}\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(red("\n\nCancelled. Nothing was written.\n"))
        sys.exit(130)
