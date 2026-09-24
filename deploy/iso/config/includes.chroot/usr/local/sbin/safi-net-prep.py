#!/usr/bin/env python3
"""First-boot network + SSH prep for a SAFi appliance.

Runs once per boot before the browser-setup and ssh services:

1. Ensures EVERY physical NIC gets an ifupdown `allow-hotplug` + DHCP stanza.
   Debian's installer only configures the NIC it used for the install; extra
   interfaces (e.g. a second LAN port, NAT, USB Ethernet) would otherwise sit
   dark. allow-hotplug hands them to udev hotplug, which brings them up with
   DHCP when carrier appears.
2. Generates SSH host keys if absent. The ssh package postinst could not run
   its keygen during the ISO build (policy-rc.d stubs daemon starts), so the
   first boot must do it or sshd refuses to start.
"""
import os
import pathlib
import re
import subprocess

PHYSICAL_NIC = re.compile(r"^(en[a-o0-9]*|e[a-z0-9]+|eth[0-9]+)$")
INTERFACES_D = pathlib.Path("/etc/network/interfaces.d")


def physical_nics() -> list[str]:
    out = []
    for name in os.listdir("/sys/class/net"):
        if name == "lo" or not PHYSICAL_NIC.match(name):
            continue
        if pathlib.Path(f"/sys/class/net/{name}/device").exists():
            out.append(name)
    return sorted(out)


def nics_already_configured() -> set[str]:
    configured: set[str] = set()
    paths = [pathlib.Path("/etc/network/interfaces")]
    paths += sorted(INTERFACES_D.glob("*")) if INTERFACES_D.is_dir() else []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("auto ") or line.startswith("allow-hotplug "):
                configured.update(line.split()[1:])
    return configured


def main() -> int:
    INTERFACES_D.mkdir(mode=0o755, exist_ok=True)
    for nic in physical_nics():
        if nic in nics_already_configured():
            continue
        stanza = f"allow-hotplug {nic}\niface {nic} inet dhcp\n"
        (INTERFACES_D / f"10-dhcp-{nic}").write_text(stanza, encoding="utf-8")
        print(f"safi-net-prep: DHCP enabled for NIC {nic}", flush=True)

    if not any(pathlib.Path("/etc/ssh").glob("ssh_host_*_key")):
        subprocess.run(["ssh-keygen", "-A"], check=True)
        print("safi-net-prep: SSH host keys generated", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())