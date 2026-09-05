#!/usr/bin/env python3
"""Sign the official TCB release registry with the owner's minisign key.

Usage:
    python scripts/tcb_sign.py static_site/tcb/releases.json \
        ~/.safi/tcb-sign.key ~/.safi/TCB_KEY.pub

Steps: append-free bump of the `sequence` field, re-serialize the list, sign
it with the legacy (raw-message) minisign format, and verify the signature
over the exact bytes a deployment will fetch. The secret key never enters the
repo; keep it offline. The list is append-only: a release is a NEW sequence,
never an edit of an old entry. Depends on the `minisign` binary being on PATH
(0.12 from https://github.com/jedisct1/minisign/releases works).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    if len(sys.argv) != 4:
        die("usage: tcb_sign.py <releases.json> <secret-key> <public-key>")
    registry, seckey, pubkey = sys.argv[1:]
    if not shutil.which("minisign"):
        die("minisign is not installed; get it from "
            "https://github.com/jedisct1/minisign/releases")
    if not os.path.isfile(seckey):
        die(f"secret key not found: {seckey}")
    if not os.path.isfile(pubkey):
        die(f"public key not found: {pubkey}")

    with open(registry, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data.get("releases"), list) or not data["releases"]:
        die("registry has no releases list")
    data["sequence"] = int(data.get("sequence") or 0) + 1
    with open(registry, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    print(f"signed sequence {data['sequence']}")
    # Legacy format: raw Ed25519 over the exact list bytes, which the
    # in-image verifier (cryptography) and minisign both reject loudly if
    # they disagree on the message.
    subprocess.run(["minisign", "-Sl", "-m", registry, "-s", seckey], check=True)
    subprocess.run(["minisign", "-Vm", registry, "-p", pubkey], check=True)
    with open(pubkey, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    print("verified: releases.json.minisig matches the public key")
    print(f"publish next to the list: releases.json + releases.json.minisig")
    print(f"site copy of {os.path.basename(pubkey)} must have sha256 {digest}")


if __name__ == "__main__":
    main()