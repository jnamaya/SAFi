#!/usr/bin/env python3
"""First-boot sanity checks + SSH host keys for a SAFi appliance.

DESIGN RULE: this script never edits an EXISTING network configuration.

/etc/network/interfaces is the single source of truth and it belongs to the
operator. The installer writes it once (DHCP by default, per preseed.cfg), and
from then on the only supported way to change it is `safi network set` +
`safi network apply`, which stages a change, shows a diff, and commits on
explicit request. A boot-time daemon that guesses an address and rewrites the
config is how a "works on my machine" appliance ends up silently pinned to the
wrong subnet in someone else's environment -- so we do not do that here.

The one exception, added after an offline install proved to brick the NIC: an
interface with NO stanza at all is given `allow-hotplug <nic> inet dhcp`. An
offline install takes netcfg's "Do not configure the network at this time"
path, which leaves the file with nothing but loopback -- so the installer tries
DHCP exactly once, and no boot after that ever tries again. The box then sits
there with a live link and no address, and the documented recovery
(`safi network set dhcp` over SSH) is unreachable, because the `admin`
password is only unlocked by the browser setup page, which needs an IP. We
therefore fill in the EMPTY case only. An interface that already has a stanza
-- static or DHCP, written by the operator or by the installer -- is never
read, rewritten, or reordered. We still never guess an address.

What this script actually does:

  1. Verifies /etc/network/interfaces is present and that every interface it
     mentions still exists. If a NIC was renamed (new kernel naming scheme,
     new driver, docking station), say so loudly and name the MAC that moved.
     It does NOT silently rewrite anything.
  2. Gives any interface that has NO stanza a DHCP-on-hotplug stanza, so an
     offline install recovers on its own once a network reappears. Existing
     stanzas are left completely alone.
  3. Generates SSH host keys if absent. The ssh postinst could not keygen
     during the ISO build because policy-rc.d stubs daemon starts.
  4. Prints the resulting address so the console banner has something to show.

Everything it reports is advisory. Exit status is always 0 unless the
interfaces file is missing outright, because failing here would wedge the
boot sequence for a problem the operator can fix with one command.
"""
import ipaddress
import os
import pathlib
import re
import subprocess
import sys

INTERFACES = pathlib.Path("/etc/network/interfaces")
STATE_DIR = pathlib.Path("/var/lib/safi-firstboot")
MAC_STATE = STATE_DIR / "nic-macs"
WPA_SUPPLICANT_CONF = pathlib.Path("/etc/wpa_supplicant/wpa_supplicant.conf")

IFACE_RE = re.compile(
    r"^\s*(?:auto|allow-hotplug|iface)\s+([A-Za-z0-9_.:@-]+)\s")

# ifup against a DHCP server that will never answer can sit there; this script
# must never be the reason a boot hangs. Bounded, and failure is ignored --
# the stanza is on disk either way, so the next boot (or the next link-up)
# retries.
IFUP_TIMEOUT = 30


def is_wireless(nic: str) -> bool:
    sys_path = pathlib.Path(f"/sys/class/net/{nic}")
    return (
        (sys_path / "wireless").is_dir()
        or (sys_path / "phy80211").is_dir()
        or nic.startswith("wl")
    )


def unblock_rfkill() -> None:
    for cmd in (["rfkill", "unblock", "wifi"], ["rfkill", "unblock", "all"]):
        try:
            subprocess.run(cmd, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            pass


def log(msg: str) -> None:
    print(f"safi-net-prep: {msg}", flush=True)


def read_stanzas() -> list[tuple[str, list[str]]]:
    """Return [(interface, block_lines)] for each iface stanza in the file."""
    if not INTERFACES.is_file():
        return []
    blocks: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    name: str | None = None
    for line in INTERFACES.read_text(encoding="utf-8", errors="replace").splitlines():
        match = IFACE_RE.match(line)
        if match:
            if name is not None and current is not None:
                blocks.append((name, current))
            name, current = match.group(1), [line]
        elif current is not None:
            current.append(line)
    if name is not None and current is not None:
        blocks.append((name, current))
    return blocks


def present_nics() -> set[str]:
    return {n for n in os.listdir("/sys/class/net") if n != "lo"}


def mac_of(nic: str) -> str | None:
    try:
        return pathlib.Path(f"/sys/class/net/{nic}/address").read_text().strip()
    except OSError:
        return None


def load_known_macs() -> dict[str, str]:
    known: dict[str, str] = {}
    if MAC_STATE.is_file():
        for line in MAC_STATE.read_text(encoding="utf-8").splitlines():
            mac, _, nic = line.partition(" ")
            if mac and nic:
                known[mac] = nic
    return known


def save_known_macs(pairs: dict[str, str]) -> None:
    # 0o700 matches safi-browser-setup.py: this directory also holds the
    # one-time setup PIN, so never create it world-readable.
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    MAC_STATE.write_text(
        "".join(f"{mac} {nic}\n" for mac, nic in sorted(pairs.items())),
        encoding="utf-8")


def check_interfaces() -> None:
    if not INTERFACES.is_file():
        log("WARNING: /etc/network/interfaces is missing.")
        log("         Run: safi network set dhcp <iface> && safi network apply")
        return

    stanzas = read_stanzas()
    present = present_nics()
    known = load_known_macs()

    # read_stanzas() now also opens a block on `auto`/`allow-hotplug` lines, so
    # one interface legitimately yields several blocks and `configured` holds
    # duplicates. Dedupe, or every repair and every report line repeats.
    configured = sorted({name for name, _ in stanzas})
    missing = [name for name in configured
               if name not in present and name != "lo"]

    for name in missing:
        # Did the hardware survive, just under a different name?
        relocated = ""
        for nic in sorted(present):
            mac = mac_of(nic)
            if mac and known.get(mac) and known[mac] != name:
                relocated = (f"  (that interface is now called '{nic}', "
                             f"MAC {mac})")
        log(f"WARNING: /etc/network/interfaces configures '{name}', "
            f"which does not exist.{relocated}")
        if relocated:
            log(f"         Fix with: safi network set <method> {nic} ... "
                f"&& safi network apply")

    # Record MACs so a future rename can be explained rather than guessed at.
    for nic in sorted(present):
        mac = mac_of(nic)
        if mac:
            known.setdefault(mac, nic)
    if known:
        save_known_macs(known)

    for name in configured:
        if name == "lo":
            continue
        method = "?"
        # Scan every block for this interface: the `inet <method>` token lives
        # on the `iface`/`allow-hotplug` line, which is not necessarily the
        # first line of the first block. Both forms are
        # `<keyword> <if> inet <method>`, hence fields[2]/fields[3].
        for block in (b for n, b in stanzas if n == name):
            for line in block:
                fields = line.split()
                if len(fields) >= 4 and fields[2] == "inet":
                    method = fields[3]
        log(f"configured: {name} -> {method}")


def ensure_dhcp_stanza() -> None:
    """Give an interface that has NO stanza at all a DHCP-on-hotplug line.

    Deliberately narrow. An interface that already has a stanza is left
    completely untouched, so this can never override a static address the
    operator set with `safi network set static ...`. The only case handled is
    the empty one left behind by an offline install: the installer tried DHCP
    once, failed, wrote a loopback-only interfaces file, and nothing has
    retried since -- leaving a box that stays unreachable even after a cable is
    plugged back in.

    `allow-hotplug` rather than `auto` on purpose: ifupdown then brings the
    interface up from the udev link event instead of during boot, so a NIC with
    no DHCP server reachable cannot hold up the boot.
    """
    present = present_nics()
    if not present:
        return

    if not INTERFACES.is_file():
        # Nothing to preserve. ifupdown needs the file to exist at all, and
        # without it the box has no address and no way to be given one.
        log(f"WARNING: {INTERFACES} is missing; creating a minimal one.")
        try:
            INTERFACES.write_text(
                "# Created by safi-net-prep: the file was missing.\n"
                "auto lo\n"
                "iface lo inet loopback\n\n", encoding="utf-8")
        except OSError as exc:
            log(f"WARNING: could not create {INTERFACES}: {exc}")
            return

    configured = {name for name, _ in read_stanzas()}
    orphans = sorted(present - configured)
    if not orphans:
        return

    for nic in orphans:
        log(f"'{nic}' has no configuration (offline install?); "
            f"requesting DHCP on link-up")

    try:
        with INTERFACES.open("a", encoding="utf-8") as handle:
            handle.write(
                "\n# Added by safi-net-prep: the interfaces above had no\n"
                "# configuration, so nothing would ever have requested an\n"
                "# address. Change with: safi network set <method> ... && "
                "safi network apply\n")
            for nic in orphans:
                if is_wireless(nic) and WPA_SUPPLICANT_CONF.is_file():
                    handle.write(
                        f"allow-hotplug {nic}\n"
                        f"iface {nic} inet dhcp\n"
                        f"    wpa-conf {WPA_SUPPLICANT_CONF}\n")
                else:
                    handle.write(f"allow-hotplug {nic} inet dhcp\n")
    except OSError as exc:
        log(f"WARNING: could not add DHCP stanzas: {exc}")
        return

    # Also check if any configured wireless interface lacks WPA configuration
    if WPA_SUPPLICANT_CONF.is_file():
        stanzas = read_stanzas()
        for name, block in stanzas:
            if name != "lo" and is_wireless(name):
                has_wpa = any(line.strip().startswith("wpa-") for line in block)
                if not has_wpa:
                    log(f"'{name}' is wireless without WPA config; attaching {WPA_SUPPLICANT_CONF}")
                    try:
                        with INTERFACES.open("a", encoding="utf-8") as handle:
                            handle.write(
                                f"\n# Added by safi-net-prep: wireless interface needs WPA authentication\n"
                                f"iface {name} inet dhcp\n"
                                f"    wpa-conf {WPA_SUPPLICANT_CONF}\n")
                    except OSError as exc:
                        log(f"WARNING: could not update wireless stanza: {exc}")

    # Try now so the current boot does not have to wait for a link toggle.
    # Bounded and best-effort: the stanza is on disk either way.
    for nic in orphans:
        try:
            out = subprocess.check_output(
                ["ip", "-4", "-o", "addr", "show", "dev", nic, "scope", "global"],
                text=True, stderr=subprocess.DEVNULL)
            if out.strip():
                log(f"'{nic}' already has IP address, skipping ifup")
                continue
        except (OSError, subprocess.SubprocessError):
            pass

        try:
            subprocess.run(["ifup", nic], timeout=IFUP_TIMEOUT,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            pass


def global_v4() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    try:
        text = subprocess.check_output(
            ["ip", "-4", "-o", "addr", "show", "scope", "global"],
            text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return out
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        try:
            addr = ipaddress.ip_interface(fields[3])
        except ValueError:
            continue
        if addr.ip.is_link_local or addr.ip.is_unspecified:
            continue
        out.append((fields[1], str(addr)))
    return out


def report_addresses() -> None:
    addresses = global_v4()
    if not addresses:
        log("no IPv4 address configured.")
        log("         Run: safi network show        (inspect)")
        log("              safi network set dhcp <iface> && safi network apply")
        return
    for nic, cidr in addresses:
        log(f"address: {cidr} on {nic}")


def ssh_keys() -> None:
    if not any(pathlib.Path("/etc/ssh").glob("ssh_host_*_key")):
        try:
            subprocess.run(["ssh-keygen", "-A"], check=True,
                           stdout=subprocess.DEVNULL)
            log("SSH host keys generated")
        except (OSError, subprocess.CalledProcessError) as exc:
            log(f"WARNING: could not generate SSH host keys: {exc}")


def main() -> int:
    unblock_rfkill()
    check_interfaces()
    # After the report above (so the operator sees the "configured:" lines
    # describing the pre-existing state) but before report_addresses(), so the
    # address summary reflects anything this boot just repaired.
    ensure_dhcp_stanza()
    ssh_keys()
    report_addresses()
    return 0


if __name__ == "__main__":
    sys.exit(main())
