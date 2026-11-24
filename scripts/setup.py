#!/usr/bin/env python3
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

VERIFY_TIMEOUT = 8

USER_AGENT = "SAFi-setup/1.0 (+https://github.com/jnamaya/SAFi)"

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
                   None),
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


def _c(code: str, s: str) -> str:
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


def gen_secret() -> str:
    return secrets.token_hex(32)


def gen_password() -> str:
    return secrets.token_urlsafe(24)


def gen_fernet_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def parse_template(path: Path) -> Tuple[List[str], Dict[str, int]]:
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
    out = list(lines)
    unknown = [k for k in values if k not in index]
    if unknown:
        raise SystemExit(red(
            "Internal error: these keys are not defined in .env.example: "
            + ", ".join(sorted(unknown))))
    for key, value in values.items():
        out[index[key]] = f"{key}={value}"
    return "\n".join(out) + "\n"


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def verify_key(provider: dict, key: str) -> Tuple[bool, str]:
    if not provider.get("verify"):
        return True, "not checked (provider has no listing endpoint)"
    url, headers_fn = provider["verify"]
    headers = {"User-Agent": USER_AGENT}
    headers.update(headers_fn(key) if headers_fn else {})
    if provider["key"] == "GEMINI_API_KEY":
        url = f"{url}?key={urllib.parse.quote(key)}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=VERIFY_TIMEOUT) as resp:
            if 200 <= resp.status < 300:
                return True, "key accepted by the provider"
            return True, f"unexpected status {resp.status} — accepting anyway"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return False, "provider rejected the key (HTTP 401 — key is not valid)"
        if e.code == 403:
            return True, ("could not check — the provider blocked the request "
                          "before looking at the key (HTTP 403)")
        return True, f"could not check (HTTP {e.code}) — accepting"
    except Exception as e:
        return True, f"could not reach the provider ({type(e).__name__}) — accepting"


def _local_tcb_fingerprint() -> str:
    try:
        import importlib.util
        checker = Path(__file__).resolve().parent / "verify_integrity.py"
        spec = importlib.util.spec_from_file_location("safi_setup_checker", checker)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        root = checker.parent.parent
        current = {}
        for rel in mod.CORE_FILES:
            f = root / rel
            if not f.exists():
                return ""
            current[rel] = mod._hash_file(f)
        return mod._root_fingerprint(current)
    except Exception:
        return ""


def ask_fingerprint_pin() -> str:
    print()
    print(dim("  Optional: if you installed from an official release, you can pin\n"
              "  this deployment to it. Copy the 'TCB Fingerprint:' line from the\n"
              "  release's notes on GitHub; every boot then re-checks the running\n"
              "  code against the value you verified, and strict mode refuses to\n"
              "  start on a mismatch. Only paste the value from the release page —\n"
              "  a fingerprint computed from this tree would pin it to itself."))
    while True:
        pin = ask("TCB Fingerprint to pin (Enter to skip)").strip().lower()
        if not pin:
            return ""
        if not re.fullmatch(r"[0-9a-f]{64}", pin):
            print(yellow("  That is not a fingerprint (expected 64 hex characters). "
                         "A truncated paste would mismatch at every boot."))
            continue
        measured = _local_tcb_fingerprint()
        if measured and measured != pin:
            print(yellow("  This tree measures a DIFFERENT fingerprint:"))
            print(yellow(f"    pinned:   {pin}"))
            print(yellow(f"    measured: {measured}"))
            print(dim("  If you cloned a branch instead of installing the release, every\n"
                      "  boot will log a pin mismatch, and strict mode will refuse to\n"
                      "  start. Install from the release tag to make them match."))
            if not ask_yes_no("Keep this pin anyway?", default=False):
                continue
        elif measured:
            print(green("  Matches this tree."))
        return pin


def collect_interactive() -> Dict[str, str]:
    values: Dict[str, str] = {}
    total = 4

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

    heading(2, total, "AI provider (optional)")
    print(dim("  SAFi can connect to Groq, Gemini, OpenAI, Anthropic, and more.\n"
              "  An API key is optional during setup — you can provide one now, or\n"
              "  skip and enter your keys later in Settings → Models & Usage."))
    print()
    provider_options = [
        (p["key"], f"{p['name']} {dim('— ' + p['note'])}", p["signup"])
        for p in PROVIDERS
    ] + [("skip", "Skip for now", "Configure API keys later in the web UI under Settings → Models & Usage")]

    chosen = ask_choice("Which provider do you want to start with?", provider_options, default=0)

    if chosen == "skip":
        print(yellow("  Skipping API key for now. You can enter your API key after\n"
                     "  logging in under Settings → Models & Usage."))
    else:
        provider = next(p for p in PROVIDERS if p["key"] == chosen)
        api_key = _read(f"  Paste your {provider['name']} API key (Enter to skip): ")
        if not api_key:
            print(yellow(f"  No key entered. You can add your {provider['name']} key later\n"
                         "  under Settings → Models & Usage."))
        else:
            while True:
                print(dim(f"  Checking the key against {provider['name']}…"))
                ok, msg = verify_key(provider, api_key)
                if ok:
                    print(green(f"  ✓ {msg}"))
                    break
                print(red(f"  ✗ {msg}"))
                retry = _read("  Paste a different key, or press Enter to keep this one: ")
                if not retry:
                    print(yellow("  Keeping key as entered."))
                    break
                api_key = retry
            if api_key:
                values[provider["key"]] = api_key

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
    values["SESSION_COOKIE_SECURE"] = "True" if base_url.startswith("https://") else "False"

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

    admin_username = ask("Admin username", "admin").strip().lower()
    admin_email = ask("Admin email address", f"{admin_username}@localhost" if admin_username else "admin@localhost")

    while True:
        admin_password = _read("  Admin password: ")
        if not admin_password:
            print(red("  Password cannot be empty. Please enter a password."))
            continue
        confirm = _read("  Confirm admin password: ")
        if admin_password != confirm:
            print(red("  Passwords do not match. Please try again."))
            continue
        break

    values["SAFI_LOCAL_ADMIN_USERNAME"] = admin_username
    values["SAFI_LOCAL_ADMIN_EMAIL"] = admin_email
    values["SAFI_LOCAL_ADMIN_PASSWORD"] = admin_password

    values["SAFI_TENANCY_MODE"] = "single"
    if login == "google":
        print(dim(f"\n  Authorized redirect URI: {base_url}/api/callback/google"))
        values["SAFI_SSO_ENABLED"] = "true"
        values["GOOGLE_CLIENT_ID"] = ask("Google client ID")
        values["GOOGLE_CLIENT_SECRET"] = ask("Google client secret")
    elif login == "microsoft":
        print(dim(f"\n  Redirect URI: {base_url}/api/callback/microsoft"))
        values["SAFI_SSO_ENABLED"] = "true"
        values["MICROSOFT_CLIENT_ID"] = ask("Microsoft client ID")
        values["MICROSOFT_CLIENT_SECRET"] = ask("Microsoft client secret")
    else:
        values["SAFI_SSO_ENABLED"] = "false"

    if is_prod:
        pin = ask_fingerprint_pin()
        if pin:
            values["SAFI_EXPECTED_FINGERPRINT"] = pin

    values.update(generated_secrets())
    values["_admin_password"] = admin_password
    return values


def generated_secrets() -> Dict[str, str]:
    return {
        "FLASK_SECRET_KEY": gen_secret(),
        "SAFI_ENCRYPTION_KEY": gen_fernet_key(),
        "DB_PASSWORD": gen_password(),
        "MYSQL_ROOT_PASSWORD": gen_password(),
        "SAFI_BOT_API_SECRET": gen_secret(),
    }


def collect_defaults() -> Dict[str, str]:
    values: Dict[str, str] = {
        "FLASK_ENV": "development",
        "SAFI_DEPLOYMENT_MODE": "trial",
        "APP_PORT": "5000",
        "WEB_BASE_URL": "http://localhost:5000",
        "ALLOWED_ORIGINS": "http://localhost:5000",
        "SESSION_COOKIE_SECURE": "False",
        "SAFI_LOCAL_ADMIN_USERNAME": os.environ.get("SAFI_LOCAL_ADMIN_USERNAME", "admin"),
        "SAFI_LOCAL_ADMIN_EMAIL": os.environ.get("SAFI_LOCAL_ADMIN_EMAIL", "admin@localhost"),
    }
    found = [p for p in PROVIDERS if os.environ.get(p["key"])]
    for p in found:
        values[p["key"]] = os.environ[p["key"]]
    values.update(generated_secrets())
    admin_password = os.environ.get("SAFI_LOCAL_ADMIN_PASSWORD") or gen_password()
    values["SAFI_LOCAL_ADMIN_PASSWORD"] = admin_password
    values["_admin_password"] = admin_password
    if found:
        print(f"Using {', '.join(p['name'] for p in found)} from the environment.")
    else:
        print(yellow("No AI provider key found in environment; configure in Settings → Models & Usage."))
    return values


def backup_path(target: Path) -> Path:
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
    if values.get("SAFI_LOCAL_ADMIN_USERNAME"):
        print(f"    username {bold(values['SAFI_LOCAL_ADMIN_USERNAME'])}")
    print(f"    email    {values['SAFI_LOCAL_ADMIN_EMAIL']}")
    print(f"    password {bold(admin_password)}")
    print(yellow("    It is stored in .env as SAFI_LOCAL_ADMIN_PASSWORD."))

    has_provider_key = any(p["key"] in values for p in PROVIDERS)
    if not has_provider_key:
        print(yellow("\n  Note: No AI provider API key was configured.\n"
                     "  Sign in to SAFi and enter your key under Settings → Models & Usage."))

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
