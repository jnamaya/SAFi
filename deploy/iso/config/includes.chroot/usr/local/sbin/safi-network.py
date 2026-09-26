#!/usr/bin/env python3
"""safi-network - declarative network configuration for the SAFi appliance.

Modeled on the Proxmox VE network model, which is the most predictable
approach available and is what operators already expect from an appliance:

  * /etc/network/interfaces is the single source of truth and it belongs to
    the operator. Every SAFi tool tries hard to preserve direct user edits;
    nothing rewrites the file behind your back.
  * Changes are STAGED to /etc/network/interfaces.new, validated, shown as a
    diff, and only committed to the live file on an explicit `apply`. A typo
    therefore cannot silently take the box off the network.
  * The same "stage, diff, apply" loop exists because a wrong network config
    makes an appliance unreachable - the exact failure we are trying to make
    impossible.

Subcommands:
  show                      current configuration, live addresses, route
  diff                      pending staged change (if any)
  set dhcp <iface>          stage DHCP on an interface
  set static <iface> <cidr> [gateway] [dns[,dns...]]
  set manual <iface>        stage "inet manual" (no address)
  set remove <iface>        stage removal of an interface stanza
  apply                     validate + commit + reload (requires --yes)
  discard                   throw away staged changes
  help
"""
from __future__ import annotations

import difflib
import ipaddress
import os
import pathlib
import re
import shutil
import subprocess
import sys

ACTIVE = pathlib.Path("/etc/network/interfaces")
STAGED = pathlib.Path("/etc/network/interfaces.new")
SYS_NET = pathlib.Path("/sys/class/net")
BACKUP = pathlib.Path("/etc/network/interfaces.safi-backup")

UNIT_RE = re.compile(
    r"^\s*(auto|allow-hotplug|iface)\s+([A-Za-z0-9_.:@-]+)\b")
SOURCE_RE = re.compile(r"^\s*source\b")

# Directories are never configured by hand, and 'lo' is managed by the base
# system. Refuse to touch them so a fat-fingered `set` cannot cut the box off.
PROTECTED = {"lo", "lo:0"}


def out(msg: str = "") -> None:
    print(msg, flush=True)


def die(msg: str, code: int = 1) -> int:
    print("error: " + msg, file=sys.stderr, flush=True)
    return code


# --- parsing -----------------------------------------------------------------
#
# The file is decomposed into a preamble, an ordered list of (iface, lines)
# stanzas, and hoisted `source` directives. Only the stanza for the interface
# being changed is replaced; every other stanza is preserved byte-for-byte so
# hand-written config on other NICs survives.

class Stanza:
    """One interface's configuration.

    `leading` holds the blank/comment lines that appear immediately ABOVE the
    stanza; `body` holds the auto/iface lines and their options. Keeping them
    apart is what lets `safi network set` replace an interface's address
    method without destroying the operator's explanatory comments.
    """

    def __init__(self, name: str, leading: list[str] | None = None,
                 body: list[str] | None = None) -> None:
        self.name = name
        self.leading = list(leading or [])
        self.body = list(body or [])

    def render(self) -> list[str]:
        return self.leading + self.body

    def describe(self) -> str:
        # "iface <name> inet <method>" -> fields[2] is the family, [3] the method.
        # `allow-hotplug` carries the same tail and is an equally complete
        # configuration, so it describes just as well -- ignoring it would make
        # `safi network show` report "?" for a NIC that is in fact on DHCP.
        for line in self.body:
            match = UNIT_RE.match(line)
            if match and match.group(1) in ("iface", "allow-hotplug"):
                fields = line.split()
                if len(fields) >= 4 and fields[2] == "inet":
                    return fields[3]
        return "?"

    def option(self, key: str) -> str | None:
        for line in self.body:
            stripped = line.strip()
            if stripped.startswith(key + " "):
                return stripped.split(None, 1)[1]
        return None


class Document:
    def __init__(self) -> None:
        self.preamble: list[str] = []
        self.stanzas: list[Stanza] = []
        self.sources: list[str] = []

    @classmethod
    def parse(cls, text: str) -> "Document":
        lines = text.splitlines()
        doc = cls()
        pending: list[str] = []      # blanks/comments awaiting a stanza
        index = 0
        while index < len(lines):
            line = lines[index]
            if SOURCE_RE.match(line):
                doc.sources.append(line)
                pending = []
                index += 1
                continue
            match = UNIT_RE.match(line)
            if not match:
                (doc.preamble if not doc.stanzas else pending).append(line)
                index += 1
                continue
            # Start a stanza. "auto X" followed by "iface X" belongs to the same
            # stanza; the first "iface <name>" (or "allow-hotplug", which
            # configures the interface just as completely) closes it.
            name = match.group(2)
            leading, pending = pending, []
            body: list[str] = []
            seen_iface = False
            while index < len(lines):
                candidate = lines[index]
                inner = UNIT_RE.match(candidate)
                if inner:
                    if inner.group(2) != name or seen_iface:
                        break
                    if inner.group(1) in ("iface", "allow-hotplug"):
                        seen_iface = True
                elif candidate.strip() and not candidate.startswith(("\t", " ")):
                    # An unindented, non-comment line ends the stanza.
                    break
                elif candidate.strip().startswith("#") and seen_iface:
                    # A comment after a completed stanza leads the next one.
                    break
                body.append(candidate)
                index += 1
            doc.stanzas.append(Stanza(name, leading, body))
        # Trailing blanks/comments at end of file belong to nobody; keep them so
        # a rewrite does not truncate the file.
        if pending:
            if doc.stanzas:
                doc.stanzas[-1].body.extend(pending)
            else:
                doc.preamble.extend(pending)
        return doc

    def render(self) -> str:
        lines: list[str] = []
        if any(line.strip() for line in self.preamble):
            lines.extend(self.preamble)
        for stanza in self.stanzas:
            if lines and lines[-1].strip():
                lines.append("")
            lines.extend(stanza.render())
        if self.sources:
            if lines and lines[-1].strip():
                lines.append("")
            lines.extend(self.sources)
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(lines) + "\n"

    def get(self, iface: str) -> Stanza | None:
        for stanza in self.stanzas:
            if stanza.name == iface:
                return stanza
        return None

    def put(self, iface: str, body: list[str]) -> None:
        """Replace an interface's body in place, preserving leading comments.

        Replacing rather than append-and-sort keeps the stanza in its original
        position, so a diff of the change is minimal and readable.
        """
        first: int | None = None
        for index, stanza in enumerate(self.stanzas):
            if stanza.name != iface:
                continue
            if first is None:
                first = index
                stanza.body = list(body)
            else:
                del self.stanzas[index]      # drop duplicate stanza
        if first is None:
            self.stanzas.append(Stanza(iface, [], body))

    def remove(self, iface: str) -> bool:
        before = len(self.stanzas)
        self.stanzas = [s for s in self.stanzas if s.name != iface]
        return len(self.stanzas) != before


def base_document() -> Document:
    """Compose onto any pending staged change so `set` calls accumulate."""
    if STAGED.is_file():
        return Document.parse(STAGED.read_text(encoding="utf-8"))
    if ACTIVE.is_file():
        return Document.parse(ACTIVE.read_text(encoding="utf-8"))
    return Document()


# --- helpers -----------------------------------------------------------------

def present_nics() -> list[str]:
    try:
        return sorted(n for n in os.listdir(SYS_NET) if n != "lo")
    except OSError:
        return []


def require_iface(iface: str) -> str | None:
    if iface in PROTECTED:
        return ("'" + iface + "' is managed by the base system and cannot "
                "be configured here")
    if iface not in present_nics():
        have = ", ".join(present_nics()) or "none detected"
        return "no such interface '" + iface + "' (detected: " + have + ")"
    return None


def render_dhcp(iface: str) -> list[str]:
    return ["auto " + iface, "iface " + iface + " inet dhcp"]


def render_manual(iface: str) -> list[str]:
    return ["auto " + iface, "iface " + iface + " inet manual"]


def render_static(iface: str, cidr: str, gateway: str | None,
                  dns: list[str]) -> list[str]:
    lines = ["auto " + iface, "iface " + iface + " inet static",
             "\taddress " + cidr]
    if gateway:
        lines.append("\tgateway " + gateway)
    if dns:
        lines.append("\tdns-nameservers " + " ".join(dns))
    return lines


# --- validation --------------------------------------------------------------

def validate(doc: Document) -> list[str]:
    problems: list[str] = []
    if not doc.stanzas:
        problems.append("configuration would contain no interface stanzas")
    nics = set(present_nics())
    for stanza in doc.stanzas:
        name = stanza.name
        if name not in nics and name not in PROTECTED:
            problems.append("interface '" + name +
                            "' does not exist on this system")
        address = stanza.option("address")
        gateway = stanza.option("gateway")
        if address:
            try:
                ipaddress.ip_interface(address)
            except ValueError:
                problems.append(name + ": '" + address +
                                "' is not a valid CIDR (expected e.g. "
                                "10.0.0.5/24)")
        if gateway:
            try:
                ipaddress.ip_address(gateway)
            except ValueError:
                problems.append(name + ": '" + gateway +
                                "' is not a valid IP address")
    return problems


# --- apply -------------------------------------------------------------------

def reload_network() -> str:
    """Apply the committed config. Returns a human-readable status."""
    # ifreload (ifupdown2) is the supported way to apply without a reboot and
    # does not tear down interfaces that did not change.
    if shutil.which("ifreload"):
        result = subprocess.run(["ifreload", "-a"], text=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        if result.returncode == 0:
            return "applied with ifreload (ifupdown2)"
        detail = (result.stdout or "").strip().splitlines()
        return "ifreload failed; reboot to apply: " + (
            detail[-1] if detail else "unknown error")
    # Plain ifupdown: bounce every interface we manage.
    for stanza in Document.parse(ACTIVE.read_text(encoding="utf-8")).stanzas:
        name = stanza.name
        if name in PROTECTED:
            continue
        for tool, args in (("ifdown", ["--force", name]), ("ifup", [name])):
            binary = shutil.which(tool) or "/sbin/" + tool
            if os.path.exists(binary):
                subprocess.run([binary] + args, check=False,
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    return "applied with ifdown/ifup (ifupdown)"


# --- subcommands -------------------------------------------------------------

def cmd_show() -> int:
    if not ACTIVE.is_file():
        return die("no /etc/network/interfaces; nothing is configured")
    doc = Document.parse(ACTIVE.read_text(encoding="utf-8"))
    nics = set(present_nics())

    out("Configured (/etc/network/interfaces):")
    for stanza in doc.stanzas:
        name = stanza.name
        if name in PROTECTED:
            continue
        flag = "" if name in nics else "   !! interface not present"
        out("  %-12s %s%s" % (name, stanza.describe(), flag))

    out()
    out("Detected interfaces:")
    for nic in present_nics():
        out("  " + nic)

    try:
        text = subprocess.check_output(
            ["ip", "-4", "-o", "addr", "show", "scope", "global"],
            text=True, stderr=subprocess.DEVNULL)
        rows = []
        for line in text.splitlines():
            fields = line.split()
            if len(fields) >= 4:
                rows.append("  %-12s %s" % (fields[1], fields[3]))
    except (OSError, subprocess.CalledProcessError):
        rows = []
    out()
    out("Live IPv4 addresses:")
    out("\n".join(rows) if rows else "  (none)")

    try:
        text = subprocess.check_output(["ip", "route", "show", "default"],
                                       text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        text = ""
    out()
    out("Default route:")
    out("\n".join("  " + line for line in text.splitlines())
        if text.strip() else "  (none)")

    if STAGED.is_file():
        out()
        out("There are STAGED changes not yet applied:")
        out("  safi network diff      review")
        out("  safi network apply     commit them")
        out("  safi network discard   throw them away")
    return 0


def cmd_diff() -> int:
    if not STAGED.is_file():
        return die("no staged changes (safi network set ... to create some)")
    old = ACTIVE.read_text(encoding="utf-8") if ACTIVE.is_file() else ""
    new = STAGED.read_text(encoding="utf-8")
    diff = difflib.unified_diff(old.splitlines(keepends=True),
                               new.splitlines(keepends=True),
                               fromfile="/etc/network/interfaces",
                               tofile="/etc/network/interfaces.new")
    rendered = "".join(diff)
    out(rendered if rendered else "(no textual difference)")
    return 0


def cmd_set(args: list[str]) -> int:
    if not args:
        return die("usage: safi network set dhcp <iface> | "
                   "safi network set static <iface> <cidr> [gateway] [dns]")
    method, rest = args[0], args[1:]

    if not rest:
        return die("usage: safi network set %s <iface> ..." % method)
    iface = rest[0]
    problem = require_iface(iface)
    if problem:
        return die(problem)

    doc = base_document()

    if method == "remove":
        if not doc.remove(iface):
            return die("'" + iface + "' has no stanza to remove")
        _write_staged(doc)
        out("staged: removed " + iface)
        _advise()
        return 0

    if method == "dhcp":
        if len(rest) != 1:
            return die("usage: safi network set dhcp <iface>")
        doc.put(iface, render_dhcp(iface))
        _write_staged(doc)
        out("staged: %s -> dhcp" % iface)
        _advise()
        return 0

    if method == "manual":
        if len(rest) != 1:
            return die("usage: safi network set manual <iface>")
        doc.put(iface, render_manual(iface))
        _write_staged(doc)
        out("staged: %s -> manual (no address)" % iface)
        _advise()
        return 0

    if method == "static":
        if len(rest) < 2:
            return die("usage: safi network set static <iface> <cidr> "
                       "[gateway] [dns[,dns...]]")
        cidr, gateway = rest[1], (rest[2] if len(rest) > 2 else None)
        dns: list[str] = []
        if len(rest) > 3:
            dns = [d for d in rest[3].split(",") if d]
        try:
            ipaddress.ip_interface(cidr)
        except ValueError as exc:
            return die("'%s' is not a valid address/prefix: %s" % (cidr, exc))
        if gateway:
            try:
                ipaddress.ip_address(gateway)
            except ValueError:
                return die("'%s' is not a valid IP address" % gateway)
        for server in dns:
            try:
                ipaddress.ip_address(server)
            except ValueError:
                return die("'%s' is not a valid IP address" % server)
        doc.put(iface, render_static(iface, cidr, gateway, dns))
        _write_staged(doc)
        out("staged: %s -> static %s%s" % (iface, cidr,
                                           (" via " + gateway) if gateway else ""))
        _advise()
        return 0

    return die("unknown method '%s' "
               "(expected dhcp, static, manual or remove)" % method)


def _write_staged(doc: Document) -> None:
    problems = validate(doc)
    if problems:
        print("error: refusing to stage an invalid configuration:",
              file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        raise SystemExit(1)
    STAGED.write_text(doc.render(), encoding="utf-8")
    STAGED.chmod(0o644)


def _advise() -> None:
    out()
    out("Not applied yet. Review with:  safi network diff")
    out("Then commit with:              safi network apply")
    out()
    out("NOTE: if you are connected over SSH, applying will drop that session.")


def cmd_apply(assume_yes: bool) -> int:
    if not STAGED.is_file():
        return die("no staged changes to apply (see: safi network diff)")
    doc = Document.parse(STAGED.read_text(encoding="utf-8"))
    problems = validate(doc)
    if problems:
        print("error: staged configuration is invalid, nothing was changed:",
              file=sys.stderr)
        for problem in problems:
            print("  - " + problem, file=sys.stderr)
        return 1

    if not assume_yes:
        out("About to replace /etc/network/interfaces. "
            "Review with 'safi network diff' first.")
        if not sys.stdin.isatty():
            return die("refusing to apply without --yes on a "
                       "non-interactive terminal")
        answer = input("Apply now? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            return die("aborted")

    if ACTIVE.is_file():
        BACKUP.write_text(ACTIVE.read_text(encoding="utf-8"),
                          encoding="utf-8")
        BACKUP.chmod(0o600)
    ACTIVE.write_text(STAGED.read_text(encoding="utf-8"), encoding="utf-8")
    ACTIVE.chmod(0o644)
    STAGED.unlink(missing_ok=True)

    out("committed to " + str(ACTIVE))
    out("previous configuration saved to " + str(BACKUP))
    out(reload_network())
    return 0


def cmd_discard() -> int:
    if not STAGED.is_file():
        return die("no staged changes to discard")
    STAGED.unlink()
    out("staged changes discarded; /etc/network/interfaces untouched")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("help", "-h", "--help"):
        out(__doc__ or "")
        return 0
    command, args = argv[0], argv[1:]
    if command == "show":
        return cmd_show()
    if command == "diff":
        return cmd_diff()
    if command == "set":
        return cmd_set(args)
    if command == "apply":
        return cmd_apply("--yes" in args)
    if command == "discard":
        return cmd_discard()
    return die("unknown subcommand '%s' "
               "(expected show, diff, set, apply, discard or help)" % command)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
