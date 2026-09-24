#!/usr/bin/env python3
"""Always-on SAFi console dashboard (tty1).

After the one-time browser setup, nothing repaints tty1 and the screen is left
stuck on the boot-log tail (fsck, kernel notices). This service takes over tty1
for the life of the machine and repaints a clean panel every few seconds:

    SAFi APPLIANCE  <ref>
    Management:    https://<ip>/
    Service status (app, KB indexer, MariaDB, Apache, SSH)
    Operator hints (SSH + virtual-console login)

It starts only after the browser-setup service has exited (After=), so the
first-boot PIN screen keeps tty1 until setup completes.
"""
import subprocess
import time
from pathlib import Path

APP_DIR = Path("/var/www/safi")
STATE_DIR = Path("/var/lib/safi-firstboot")
PIN_FILE = STATE_DIR / "setup.pin"
DONE_FILE = STATE_DIR / "done"

CLEAR = "\x1b[2J\x1b[H"
BOLD = "\x1b[1m"
GREEN = "\x1b[32m"
RED = "\x1b[31m"
YELLOW = "\x1b[33m"
RESET = "\x1b[0m"

SERVICES = ["safi", "safi-kb-indexer", "mariadb", "apache2", "ssh"]


def local_ip() -> str:
    # Same ordering as the setup wizard: enumerate the management NIC first, so
    # the URL shown on the console matches the address a browser can reach.
    try:
        addrs = subprocess.check_output(
            ["ip", "-4", "-o", "addr", "show", "scope", "global"], text=True)
        for line in addrs.splitlines():
            tokens = line.split()
            if len(tokens) >= 4:
                return tokens[3].split("/")[0]
    except Exception:
        pass
    try:
        route = subprocess.check_output(["ip", "route", "get", "1.1.1.1"], text=True)
        fields = route.split()
        return fields[fields.index("src") + 1]
    except Exception:
        pass
    return "<appliance-ip>"


def service_state(name: str) -> str:
    try:
        out = subprocess.check_output(
            ["systemctl", "is-active", name], text=True, errors="replace").strip()
        if out == "active":
            return f"{GREEN}UP{RESET}"
        if out == "failed":
            return f"{RED}FAILED{RESET}"
        return f"{YELLOW}{out.upper()}{RESET}"
    except Exception:
        return f"{YELLOW}?{RESET}"


def appliance_ref() -> str:
    env = STATE_DIR / "build.env"
    if env.exists():
        for line in env.read_text(errors="replace").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "SAFI_REF":
                ref = value.strip().strip('"').strip("'")
                if ref:
                    return ref
    return "v1.4.1"


def management_url() -> str:
    # The setup wizard wrote WEB_BASE_URL into .env (the URL the browser
    # actually uses). Prefer it — local_ip() can pick the wrong leg of a
    # multi-homed box (e.g. the NAT NIC) for the operator-facing address.
    env = APP_DIR / ".env"
    if env.exists():
        for line in env.read_text(errors="replace").splitlines():
            key, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'")
            if key.strip() == "WEB_BASE_URL" and value.startswith("https://"):
                return value.rstrip("/")
    return f"https://{local_ip()}/"


def render() -> str:
    ref = appliance_ref()
    configured = DONE_FILE.exists()
    url = management_url().rstrip("/")
    host = url.split("/")[-1]

    dot = f"{GREEN}\u25cf{RESET}"
    lines = [
        "",
        f"  {BOLD}SAFi APPLIANCE{RESET}  {ref}{' ' * 36}{dot}",
        "  " + "=" * 74,
        "",
        f"  Management UI : {BOLD}{url}{RESET}",
        "  API health   : " + url + "/api/health",
        "",
        "  Services",
    ]
    for svc in SERVICES:
        lines.append(f"    {svc:<18} {service_state(svc)}")
    lines += [
        "",
         "  Operator access",
         f"    SSH      : ssh admin@{host}",
        "",
        "  " + "=" * 74,
    ]
    if not configured:
        pin = PIN_FILE.read_text(errors="replace").strip() if PIN_FILE.exists() else "(see first boot)"
        lines += [
            "",
            f"  {BOLD}This appliance is not configured yet.{RESET}",
            f"  Open {BOLD}{url}{RESET} in a browser to run the SAFi setup wizard.",
            f"  One-time PIN: {BOLD}{pin}{RESET}",
        ]
    else:
        lines += [
            "",
            "  Configured. The app serves at the Management UI address above.",
            "  The web admin and the 'admin' OS account share one password.",
        ]
    lines += ["", ""]
    return "\r\n".join(lines) + "\r\n"


def main() -> int:
    while True:
        print(CLEAR + render(), end="", flush=True)
        time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())
