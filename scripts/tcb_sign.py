#!/usr/bin/env python3
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
    subprocess.run(["minisign", "-Sl", "-m", registry, "-s", seckey], check=True)
    subprocess.run(["minisign", "-Vm", registry, "-p", pubkey], check=True)
    with open(pubkey, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    print("verified: releases.json.minisig matches the public key")
    print(f"publish next to the list: releases.json + releases.json.minisig")
    print(f"site copy of {os.path.basename(pubkey)} must have sha256 {digest}")


if __name__ == "__main__":
    main()