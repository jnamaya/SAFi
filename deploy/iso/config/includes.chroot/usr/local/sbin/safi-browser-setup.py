#!/usr/bin/env python3
"""One-time HTTPS bootstrap for a SAFi appliance."""
from __future__ import annotations

import html
import importlib.util
import os
import secrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

APP_DIR = Path("/var/www/safi")
STATE_DIR = Path("/var/lib/safi-firstboot")
PIN_FILE = STATE_DIR / "setup.pin"
DONE_FILE = STATE_DIR / "done"
ENV_FILE = APP_DIR / ".env"
HOST = "127.0.0.1"
PORT = 5001


def load_setup_module():
    spec = importlib.util.spec_from_file_location("runsafi_setup", APP_DIR / "scripts/setup.py")
    if not spec or not spec.loader:
        raise RuntimeError("SAFi setup helpers are unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ensure_certificate() -> tuple[Path, Path]:
    cert_dir = Path("/etc/ssl/runsafi")
    cert_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = cert_dir / "appliance.key"
    cert = cert_dir / "appliance.crt"
    if not key.exists() or not cert.exists():
        subprocess.run([
            "openssl", "req", "-x509", "-nodes", "-newkey", "rsa:3072",
            "-days", "3650", "-keyout", str(key), "-out", str(cert),
            "-subj", "/CN=SAFi Appliance",
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        key.chmod(0o600)
        cert.chmod(0o644)
    return cert, key


def local_ip(retries: int = 1) -> str:
    # The operator browses the appliance over its management/LAN NIC, not the
    # egress NIC a NAT/router would answer for `ip route get`. Enumerate the
    # host's global IPv4 addresses first (kernel PCI order: eth0/enp0s3 before
    # a NAT NIC) so WEB_BASE_URL points at the address a browser can reach;
    # fall back to the routable source only if enumeration fails.
    for attempt in range(retries):
        try:
            addrs = subprocess.check_output(
                ["ip", "-4", "-o", "addr", "show", "scope", "global"], text=True)
            for line in addrs.splitlines():
                tokens = line.split()
                if len(tokens) >= 4:
                    return tokens[3].split("/")[0]
        except Exception:
            pass
        if attempt + 1 < retries:
            time.sleep(1)
    try:
        route = subprocess.check_output(["ip", "route", "get", "1.1.1.1"], text=True)
        fields = route.split()
        return fields[fields.index("src") + 1]
    except Exception:
        pass
    return "<appliance-ip>"


def form_page(error: str = "") -> str:
    message = f'<div class="error">{html.escape(error)}</div>' if error else ""
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SAFi Appliance Setup</title>
<style>
:root{{--bg:#111827;--panel:#1f2937;--line:#374151;--green:#16a34a;--bright:#22c55e;--muted:#9ca3af}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:#f9fafb;font:16px system-ui,sans-serif}}
main{{width:min(680px,calc(100% - 32px));background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:32px;box-shadow:0 20px 60px #0006}}
.mark{{color:var(--bright);font-weight:800;letter-spacing:.08em;text-transform:uppercase}}h1{{margin:.4rem 0 .5rem}}p{{color:var(--muted);line-height:1.5}}
label{{display:block;margin:18px 0 6px;font-weight:600}}input,select{{width:100%;padding:12px;border:1px solid var(--line);border-radius:8px;background:#111827;color:#fff;font:inherit}}
button{{margin-top:24px;width:100%;border:0;border-radius:8px;padding:13px;background:var(--green);color:#fff;font-weight:700;font-size:1rem;cursor:pointer}}
button:hover{{background:var(--bright);color:#052e16}}.error{{margin:16px 0;padding:12px;border:1px solid #ef4444;color:#fecaca;border-radius:8px}}small{{color:var(--muted)}}
</style></head><body><main><div class="mark">SAFi</div><h1>Appliance setup</h1>
<p>Configure this appliance from the local network. Setup initializes the database and starts the governance engine.</p>
{message}<form method="post" action="/setup">
<label for="pin">One-time setup PIN</label><input id="pin" name="pin" required inputmode="numeric" autocomplete="one-time-code">
<label for="provider">AI provider</label><select id="provider" name="provider">
<option value="GROQ_API_KEY">Groq</option><option value="OPENAI_API_KEY">OpenAI</option><option value="ANTHROPIC_API_KEY">Anthropic</option><option value="GEMINI_API_KEY">Google Gemini</option><option value="MISTRAL_API_KEY">Mistral</option><option value="DEEPSEEK_API_KEY">DeepSeek</option><option value="CEREBRAS_API_KEY">Cerebras</option><option value="ZHIPU_API_KEY">Zhipu / GLM</option></select>
<label for="api_key">Provider API key</label><input id="api_key" name="api_key" type="password" required autocomplete="off">
<label for="email">Administrator email</label><input id="email" name="email" type="email" value="admin@localhost" required>
<label for="password">Administrator password</label><input id="password" name="password" type="password" minlength="12" required autocomplete="new-password">
<label for="password_confirm">Confirm administrator password</label><input id="password_confirm" name="password_confirm" type="password" minlength="12" required autocomplete="new-password">
<button type="submit">Initialize SAFi</button></form><p><small>Open https://{html.escape(local_ip())}/. The certificate is generated locally; replace it with your enterprise certificate after setup.</small></p>
</main></body></html>'''


def initialize(fields: dict[str, str], setup) -> None:
    if fields["password"] != fields["password_confirm"]:
        raise ValueError("Administrator passwords do not match")
    if len(fields["password"]) < 12:
        raise ValueError("Administrator password must be at least 12 characters")
    if not fields["api_key"].strip():
        raise ValueError("Provider API key is required")

    lines, index = setup.parse_template(APP_DIR / ".env.example")
    base_url = f"https://{local_ip()}"
    values = {
        "FLASK_ENV": "production", "SAFI_DEPLOYMENT_MODE": "production",
        "APP_PORT": str(PORT), "WEB_BASE_URL": base_url,
        "ALLOWED_ORIGINS": base_url, "SESSION_COOKIE_SECURE": "True",
        "DB_HOST": "localhost", "DB_USER": "safi", "DB_NAME": "safi",
        "SAFI_LOCAL_ADMIN_EMAIL": fields["email"].strip(),
        "SAFI_LOCAL_ADMIN_PASSWORD": fields["password"],
        fields["provider"]: fields["api_key"].strip(),
    }
    values.update(setup.generated_secrets())
    tmp = ENV_FILE.with_suffix(".env.tmp")
    tmp.write_text(setup.render(lines, index, values), encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, ENV_FILE)
    # This service writes .env as root, but safi.service / safi-kb-indexer run
    # as safi:www-data; without a chown gunicorn dies on the first dotenv read
    # (PermissionError) and apache serves 503. Keep it 0600, owned by safi.
    subprocess.run(
        ["chown", "safi:www-data", str(ENV_FILE)], check=True)

    subprocess.run(["systemctl", "start", "mysql"], check=True)
    db_password = values["DB_PASSWORD"].replace("'", "''")
    root_password = values["MYSQL_ROOT_PASSWORD"].replace("'", "''")
    sql = (
        "CREATE DATABASE IF NOT EXISTS `safi` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; "
        # Scratch schema for backup restore-verification (backup_verify.py). It
        # is provisioned up-front so the minimal `safi` DB account never needs
        # database-level CREATE; the verifier wipes it by dropping its tables.
        "CREATE DATABASE IF NOT EXISTS `safi_verify` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; "
        f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{root_password}'; "
        f"CREATE USER IF NOT EXISTS 'safi'@'localhost' IDENTIFIED BY '{db_password}'; "
        f"ALTER USER 'safi'@'localhost' IDENTIFIED BY '{db_password}'; "
        "GRANT ALL PRIVILEGES ON `safi`.* TO 'safi'@'localhost'; "
        "GRANT ALL PRIVILEGES ON `safi_verify`.* TO 'safi'@'localhost'; FLUSH PRIVILEGES;"
    )
    subprocess.run(["mysql", "--protocol=socket", "-u", "root", "-e", sql], check=True)
    # Operator account (console + SSH): the appliance admin password unlocks
    # the `admin` OS user created by 020-accounts-and-dirs.chroot. One
    # password governs both the web admin login and the box itself.
    admin_password = fields["password"]
    subprocess.run(
        ["bash", "-c",
         f"printf '%s\\n' 'admin:{admin_password}' | chpasswd"], check=True)
    PIN_FILE.unlink(missing_ok=True)
    DONE_FILE.touch(mode=0o600, exist_ok=True)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/") != "/setup":
            self.send_response(302); self.send_header("Location", "/setup"); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
        self.wfile.write(form_page().encode())

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        fields = {key: values[0] for key, values in parse_qs(self.rfile.read(length).decode(), keep_blank_values=True).items()}
        if not secrets.compare_digest(fields.get("pin", ""), self.server.pin):
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
            self.wfile.write(form_page("Invalid or expired setup PIN.").encode()); return
        try:
            initialize(fields, self.server.setup)
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
            self.wfile.write(b"<h1>SAFi is starting</h1><p>Refresh this address in about one minute.</p>")
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        except Exception as exc:
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
            self.wfile.write(form_page(str(exc)).encode())

    def log_message(self, *_args):
        return


def main() -> int:
    if DONE_FILE.exists():
        return 0
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not PIN_FILE.exists():
        PIN_FILE.write_text(f"{secrets.randbelow(1_000_000):06d}\n", encoding="ascii")
        PIN_FILE.chmod(0o600)
    pin = PIN_FILE.read_text(encoding="ascii").strip()
    cert, key = ensure_certificate()
    setup = load_setup_module()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.pin = pin; server.setup = setup
    # Print the banner FIRST: the PIN must reach the console even if apache has
    # a hiccup, otherwise a boot looks frozen with no way in. Apache is what
    # serves https://IP/ -> 127.0.0.1:5001; its failure must never be fatal
    # here (a PIN worth of bricked console is worse than a retry).
    # DHCP can finish just after network-online.target on appliances with more
    # than one NIC. Wait briefly so the console shows a usable URL, not a
    # permanent <appliance-ip> placeholder.
    print(f"SAFi Appliance is Active. Complete configuration at: https://{local_ip(60)}/", flush=True)
    print(f"One-time setup PIN: {pin}", flush=True)
    try:
        subprocess.run(["systemctl", "enable", "--now", "apache2"], check=True)
    except subprocess.CalledProcessError as exc:
        print(f"warning: apache2 could not be started ({exc.returncode}); "
              "https://<ip>/ will be unavailable until it is.", flush=True)
    server.serve_forever()
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", "safi", "safi-kb-indexer"], check=True)
    subprocess.run(["systemctl", "enable", "safi-retention-purge.timer", "safi-backup.timer", "safi-backup-verify.timer"], check=True)
    # Keep the status dashboard on tty1 after first boot. It is informational
    # only; local console login is intentionally disabled there.
    subprocess.run(["systemctl", "start", "safi-console"], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
