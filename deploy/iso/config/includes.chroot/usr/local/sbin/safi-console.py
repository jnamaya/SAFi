#!/usr/bin/env python3
"""Always-on SAFi console dashboard (tty1).

After the one-time browser setup, this service takes over tty1 for the life
of the machine and displays a clean status panel, live interactive network
reconfiguration (Wi-Fi scanning/connecting, wired DHCP/static, diagnostics),
and an interactive root diagnostic shell.
"""
import os
import re
import select
import subprocess
import sys
import time
from pathlib import Path

APP_DIR = Path("/var/www/safi")
STATE_DIR = Path("/var/lib/safi-firstboot")
DONE_FILE = STATE_DIR / "done"
CERT_DIR = Path("/etc/ssl/runsafi")
CERT_FILE = CERT_DIR / "appliance.crt"

CLEAR = "\x1b[2J\x1b[H"
BOLD = "\x1b[1m"
GREEN = "\x1b[32m"
RED = "\x1b[31m"
YELLOW = "\x1b[33m"
CYAN = "\x1b[36m"
RESET = "\x1b[0m"

SERVICES = ["safi", "safi-kb-indexer", "mariadb", "apache2", "ssh"]


def local_ip(retries: int = 1) -> str:
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
    env = APP_DIR / ".env"
    if env.exists():
        for line in env.read_text(errors="replace").splitlines():
            key, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'")
            if key.strip() == "WEB_BASE_URL" and value.startswith("https://"):
                return value.rstrip("/")
    return f"https://{local_ip()}/"


def ensure_certificate(ip_address: str | None = None) -> tuple[Path, Path]:
    cert_dir = CERT_DIR
    cert_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = cert_dir / "appliance.key"
    cert = CERT_FILE
    address = ip_address if ip_address is not None else local_ip()
    expected_dns = ("safi.local", "runsafi.local")

    def matches_current_names() -> bool:
        if not key.is_file() or not cert.is_file():
            return False
        try:
            sans = subprocess.run(
                ["openssl", "x509", "-in", str(cert), "-noout", "-ext", "subjectAltName"],
                check=True, capture_output=True, text=True,
            ).stdout
            constraints = subprocess.run(
                ["openssl", "x509", "-in", str(cert), "-noout", "-ext", "basicConstraints"],
                check=True, capture_output=True, text=True,
            ).stdout
            subprocess.run(
                ["openssl", "x509", "-in", str(cert), "-checkend", "0", "-noout"],
                check=True, capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return False
        if "CA:TRUE" not in constraints or any(f"DNS:{name}" not in sans for name in expected_dns):
            return False
        if address and address != "<appliance-ip>":
            return re.search(rf"IP Address:\s*{re.escape(address)}(?:\s|,|$)", sans) is not None
        return True

    if not matches_current_names():
        san = [*(f"DNS:{name}" for name in expected_dns)]
        if address and address != "<appliance-ip>":
            san.append(f"IP:{address}")
        new_key = cert_dir / "appliance.key.new"
        new_cert = cert_dir / "appliance.crt.new"
        new_key.unlink(missing_ok=True)
        new_cert.unlink(missing_ok=True)
        try:
            subprocess.run([
                "openssl", "req", "-x509", "-nodes", "-newkey", "rsa:3072",
                "-days", "3650", "-keyout", str(new_key), "-out", str(new_cert),
                "-subj", "/CN=SAFi Appliance",
                "-addext", f"subjectAltName={','.join(san)}",
                "-addext", "basicConstraints=critical,CA:TRUE",
                "-addext", "keyUsage=critical,digitalSignature,keyCertSign,cRLSign",
                "-addext", "extendedKeyUsage=serverAuth",
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            new_key.chmod(0o600)
            new_cert.chmod(0o644)
            os.replace(new_key, key)
            os.replace(new_cert, cert)
        finally:
            new_key.unlink(missing_ok=True)
            new_cert.unlink(missing_ok=True)
    return cert, key


def update_web_base_url(ip_address: str) -> None:
    env = APP_DIR / ".env"
    if env.exists():
        try:
            lines = env.read_text(encoding="utf-8", errors="replace").splitlines()
            new_lines = []
            found = False
            for line in lines:
                if line.strip().startswith("WEB_BASE_URL="):
                    new_lines.append(f"WEB_BASE_URL=https://{ip_address}")
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f"WEB_BASE_URL=https://{ip_address}")
            env.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        except Exception:
            pass


def find_all_interfaces() -> dict[str, str]:
    """Return {iface_name: 'wireless' | 'ethernet'} for physical network devices."""
    nics: dict[str, str] = {}
    sys_net = Path("/sys/class/net")
    if sys_net.exists():
        for p in sorted(sys_net.iterdir()):
            name = p.name
            if name == "lo":
                continue
            if (p / "wireless").is_dir() or (p / "phy80211").is_dir() or name.startswith("wl"):
                nics[name] = "wireless"
            else:
                nics[name] = "ethernet"
    return nics


def connect_wifi(iface: str, ssid: str, psk: str) -> None:
    print(f"\nConfiguring wpa_supplicant on {iface} for '{ssid}'...")
    wpa_conf = Path("/etc/wpa_supplicant/wpa_supplicant.conf")
    wpa_conf.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev\n"
        "update_config=1\n"
        "country=US\n\n"
        "network={\n"
        f'    ssid="{ssid}"\n'
        f'    psk="{psk}"\n'
        "    key_mgmt=WPA-PSK WPA-PSK-SHA256\n"
        "    priority=1\n"
        "}\n"
    )
    wpa_conf.write_text(content, encoding="utf-8")
    wpa_conf.chmod(0o600)

    # Stop any conflicting wpa_supplicant
    subprocess.run(["killall", "wpa_supplicant"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sock = Path(f"/var/run/wpa_supplicant/{iface}")
    if sock.exists():
        try:
            sock.unlink()
        except OSError:
            pass

    print(f"Starting wpa_supplicant on {iface}...")
    subprocess.run(["wpa_supplicant", "-B", "-i", iface, "-c", str(wpa_conf), "-D", "nl80211,wext"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print("Waiting for Wi-Fi association (up to 15s)...")
    connected = False
    for i in range(15):
        try:
            status = subprocess.check_output(["wpa_cli", "-i", iface, "status"], text=True, stderr=subprocess.DEVNULL)
            for line in status.splitlines():
                if line.startswith("wpa_state="):
                    state = line.split("=")[1].strip()
                    print(f"  Attempt {i+1}/15: wpa_state={state}")
                    if state == "COMPLETED":
                        connected = True
                        break
        except Exception:
            pass
        if connected:
            break
        time.sleep(1)

    if not connected:
        print(f"[!] Warning: Association with '{ssid}' did not reach COMPLETED.")
        print("    Attempting DHCP anyway in case link established...")
    else:
        print(f"[✓] Associated successfully with '{ssid}'! Requesting DHCP lease...")

    # Run DHCP
    print(f"Running dhclient on {iface}...")
    subprocess.run(["dhclient", "-4", "-v", iface], check=False)
    time.sleep(2)

    new_ip = local_ip(5)
    if new_ip != "<appliance-ip>":
        print(f"\n[✓] SUCCESS! Acquired IP address: {new_ip}")
        ensure_certificate(new_ip)
        update_web_base_url(new_ip)
        subprocess.run(["systemctl", "reload", "apache2"], check=False)
        # Update /etc/network/interfaces permanently
        try:
            ifaces_file = Path("/etc/network/interfaces")
            text = ifaces_file.read_text(encoding="utf-8", errors="replace")
            if f"iface {iface}" not in text:
                with ifaces_file.open("a", encoding="utf-8") as h:
                    h.write(f"\nallow-hotplug {iface}\niface {iface} inet dhcp\n    wpa-conf /etc/wpa_supplicant/wpa_supplicant.conf\n")
        except Exception as e:
            print(f"Note: could not update /etc/network/interfaces: {e}")
        print(f"\nAppliance is active at: https://{new_ip}/")
    else:
        print("\n[!] Could not acquire an IP address via DHCP.")


def menu_setup_wifi(nics: dict[str, str]) -> None:
    wl_nics = [n for n, t in nics.items() if t == "wireless"]
    if not wl_nics:
        print("\n[!] No wireless network interfaces detected by kernel.")
        print("    Check Diagnostics menu option to verify if Wi-Fi card requires driver.")
        input("\nPress Enter to return to menu...")
        return

    if len(wl_nics) == 1:
        iface = wl_nics[0]
    else:
        print("\nSelect wireless interface:")
        for idx, n in enumerate(wl_nics, 1):
            print(f"  {idx}) {n}")
        sel = input("Enter choice [1]: ").strip() or "1"
        try:
            iface = wl_nics[int(sel) - 1]
        except (ValueError, IndexError):
            iface = wl_nics[0]

    print(f"\nUnblocking radio and bringing up {iface}...")
    subprocess.run(["rfkill", "unblock", "all"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "link", "set", iface, "up"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)

    print("Scanning for wireless networks...")
    ssids: list[str] = []
    try:
        scan_out = subprocess.check_output(
            ["iw", "dev", iface, "scan"], text=True, stderr=subprocess.DEVNULL, timeout=10)
        for line in scan_out.splitlines():
            line = line.strip()
            if line.startswith("SSID: ") and len(line) > 6:
                s = line[6:].strip()
                if s and s not in ssids:
                    ssids.append(s)
    except Exception:
        pass

    chosen_ssid = ""
    if ssids:
        print("\nDiscovered Wi-Fi Networks:")
        for idx, s in enumerate(ssids, 1):
            print(f"  {idx}) {s}")
        print(f"  {len(ssids) + 1}) Enter custom or hidden SSID")
        sel = input(f"Choose network [1-{len(ssids)+1}] or enter SSID [default: Amaya]: ").strip()
        if not sel:
            chosen_ssid = "Amaya"
        elif sel.isdigit() and 1 <= int(sel) <= len(ssids):
            chosen_ssid = ssids[int(sel) - 1]
        elif sel.isdigit() and int(sel) == len(ssids) + 1:
            chosen_ssid = input("Enter SSID: ").strip() or "Amaya"
        else:
            chosen_ssid = sel
    else:
        print("No networks automatically returned by scan.")
        chosen_ssid = input("Enter Wi-Fi SSID [default: Amaya]: ").strip() or "Amaya"

    psk = input(f"Enter Wi-Fi Password for '{chosen_ssid}' [default: sabino07]: ").strip()
    if not psk:
        psk = "sabino07"

    connect_wifi(iface, chosen_ssid, psk)
    input("\nPress Enter to return to menu...")


def menu_autoconnect_wifi(nics: dict[str, str], ssid: str = "Amaya", psk: str = "sabino07") -> None:
    wl_nics = [n for n, t in nics.items() if t == "wireless"]
    if not wl_nics:
        print("\n[!] No wireless interfaces found.")
        input("Press Enter to return to menu...")
        return
    iface = wl_nics[0]
    print(f"\nAuto-connecting {iface} to '{ssid}'...")
    subprocess.run(["rfkill", "unblock", "all"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["ip", "link", "set", iface, "up"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    connect_wifi(iface, ssid, psk)
    input("\nPress Enter to return to menu...")


def menu_setup_ethernet(nics: dict[str, str]) -> None:
    eth_nics = [n for n, t in nics.items() if t == "ethernet"]
    if not eth_nics:
        print("\n[!] No wired ethernet interfaces found.")
        input("Press Enter to return to menu...")
        return
    if len(eth_nics) == 1:
        iface = eth_nics[0]
    else:
        print("\nSelect ethernet interface:")
        for idx, n in enumerate(eth_nics, 1):
            print(f"  {idx}) {n}")
        sel = input("Enter choice [1]: ").strip() or "1"
        try:
            iface = eth_nics[int(sel) - 1]
        except (ValueError, IndexError):
            iface = eth_nics[0]

    print(f"\nBringing up {iface} and requesting DHCP...")
    subprocess.run(["ip", "link", "set", iface, "up"], check=False)
    subprocess.run(["dhclient", "-4", "-v", iface], check=False)
    time.sleep(2)
    new_ip = local_ip(5)
    if new_ip != "<appliance-ip>":
        print(f"\n[✓] SUCCESS! Acquired IP address: {new_ip}")
        ensure_certificate(new_ip)
        update_web_base_url(new_ip)
        subprocess.run(["systemctl", "reload", "apache2"], check=False)
        try:
            ifaces_file = Path("/etc/network/interfaces")
            text = ifaces_file.read_text(encoding="utf-8", errors="replace")
            if f"iface {iface}" not in text:
                with ifaces_file.open("a", encoding="utf-8") as h:
                    h.write(f"\nallow-hotplug {iface} inet dhcp\n")
        except Exception:
            pass
        print(f"\nAppliance is active at: https://{new_ip}/")
    else:
        print("\n[!] Could not acquire an IP address via DHCP. Check cable.")
    input("\nPress Enter to return to menu...")


def menu_setup_static(nics: dict[str, str]) -> None:
    all_nics = list(nics.keys())
    if not all_nics:
        print("\n[!] No network interfaces found.")
        input("Press Enter to return to menu...")
        return
    print("\nAvailable interfaces:", ", ".join(all_nics))
    iface = input(f"Interface name [{all_nics[0]}]: ").strip() or all_nics[0]
    cidr = input("IP Address with CIDR (e.g. 192.168.1.150/24): ").strip()
    if not cidr:
        print("IP/CIDR is required.")
        input("Press Enter to continue...")
        return
    gateway = input("Gateway IP (e.g. 192.168.1.1) [optional]: ").strip()
    dns = input("DNS Server(s) (e.g. 1.1.1.1,8.8.8.8) [optional]: ").strip()

    try:
        subprocess.run(["ip", "link", "set", iface, "up"], check=True)
        subprocess.run(["ip", "addr", "flush", "dev", iface], check=False)
        subprocess.run(["ip", "addr", "add", cidr, "dev", iface], check=True)
        if gateway:
            subprocess.run(["ip", "route", "add", "default", "via", gateway, "dev", iface], check=False)
        if dns:
            resolv = Path("/etc/resolv.conf")
            nameservers = [f"nameserver {d.strip()}" for d in dns.split(",")]
            resolv.write_text("\n".join(nameservers) + "\n", encoding="utf-8")
        ip_only = cidr.split("/")[0]
        ensure_certificate(ip_only)
        update_web_base_url(ip_only)
        subprocess.run(["systemctl", "reload", "apache2"], check=False)
        print(f"\n[✓] Static IP configured! Appliance reachable at: https://{ip_only}/")
    except Exception as e:
        print(f"\n[!] Failed to set static IP: {e}")
    input("\nPress Enter to return to menu...")


def menu_diagnostics() -> None:
    print("\n" + "=" * 76)
    print("                     NETWORK & HARDWARE DIAGNOSTICS")
    print("=" * 76)
    print("--- Network Interfaces (ip -br a) ---")
    subprocess.run(["ip", "-br", "a"])
    print("\n--- Routing Table (ip r) ---")
    subprocess.run(["ip", "r"])
    print("\n--- RFKILL Status ---")
    subprocess.run(["rfkill", "list"])
    print("\n--- Network Hardware (lspci) ---")
    subprocess.run("lspci -nnk | grep -iA3 -E 'network|wireless|ethernet'", shell=True)
    print("\n--- Recent Wireless/Firmware Kernel Logs (dmesg) ---")
    subprocess.run("dmesg | grep -iE 'wifi|wlan|ath|iwl|rtw|firmware' | tail -n 25", shell=True)
    print("=" * 76)
    input("\nPress Enter to return to menu...")


def run_network_manager() -> None:
    while True:
        address = local_ip(1)
        nics = find_all_interfaces()

        print(CLEAR, end="")
        print("=" * 76)
        print("                 SAFi Network Configuration & Manager")
        print("=" * 76)
        print(f"  Current Address : {address}")
        print(f"  Management UI   : https://{address}/")
        print("-" * 76)
        print("  Detected Interfaces:")
        if not nics:
            print("    (No physical network interfaces found by Linux kernel)")
        else:
            for n, t in nics.items():
                try:
                    ip_out = subprocess.check_output(
                        ["ip", "-4", "-o", "addr", "show", "dev", n, "scope", "global"],
                        text=True, stderr=subprocess.DEVNULL)
                    ip_str = ip_out.split()[3] if ip_out.strip() else "no IP"
                except Exception:
                    ip_str = "no IP"
                print(f"    - {n:<12} ({t:<8}) -> {ip_str}")
        print("-" * 76)
        print("  1) Connect to Wi-Fi (Scan / Select / Enter Password)")
        print("  2) Auto-connect to Preconfigured Wi-Fi (\"Amaya\")")
        print("  3) Configure Wired Network (DHCP)")
        print("  4) Configure Static IP Address")
        print("  5) Show Network Diagnostics & Driver Logs")
        print("  6) Run 'safi network show' (System config)")
        print("  0) Return to Main Dashboard")
        print("=" * 76)

        try:
            choice = input("\nSelect option [0-6]: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if choice in ("0", "q", "exit"):
            break
        elif choice == "1":
            menu_setup_wifi(nics)
        elif choice == "2":
            menu_autoconnect_wifi(nics, ssid="Amaya", psk="sabino07")
        elif choice == "3":
            menu_setup_ethernet(nics)
        elif choice == "4":
            menu_setup_static(nics)
        elif choice == "5":
            menu_diagnostics()
        elif choice == "6":
            print(CLEAR + "\nRunning 'safi network show'...\n")
            subprocess.run(["/usr/local/sbin/safi", "network", "show"])
            input("\nPress Enter to return to menu...")


def run_root_shell() -> None:
    print(CLEAR + "\nOpening root diagnostic shell. Type 'exit' to return to dashboard.\n")
    env = os.environ.copy()
    env["PS1"] = "root@safi:~# "
    env["TERM"] = "linux"
    try:
        subprocess.run(["/bin/bash", "-i"], env=env)
    except Exception as e:
        print(f"Shell execution error: {e}")
        time.sleep(2)
    print("\nReturned from root shell.")
    time.sleep(1)


def render_dashboard() -> str:
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
        lines += [
            "",
            f"  {BOLD}This appliance is not configured yet.{RESET}",
            f"  Open {BOLD}{url}{RESET} in a browser to run the SAFi setup wizard.",
        ]
    else:
        lines += [
            "",
            "  Configured. The app serves at the Management UI address above.",
            "  The web admin and the 'admin' OS account share one password.",
        ]
    lines += [
        "",
        "  " + "-" * 74,
        f"  {BOLD}Console options:{RESET} [n]+Enter for Network Reconfiguration",
        "                   [s]+Enter for Root Diagnostic Shell",
        "  " + "-" * 74,
        "",
    ]
    return "\r\n".join(lines) + "\r\n"


def main() -> int:
    while True:
        print(CLEAR + render_dashboard(), end="", flush=True)
        if sys.stdin.isatty():
            r, _, _ = select.select([sys.stdin], [], [], 3.0)
            if r:
                line = sys.stdin.readline().strip().lower()
                if line == "s":
                    run_root_shell()
                elif line == "n":
                    run_network_manager()
        else:
            time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())
