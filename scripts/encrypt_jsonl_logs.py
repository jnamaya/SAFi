#!/usr/bin/env python3
"""Encrypt legacy plaintext JSONL governance logs in place (Phase F residual).

The system of record for per-turn governance data is the encrypted
governance_records table (2026-07-21, native Audit Hub); JSONL disk logging
is a debug sink that now defaults off. This script closes out the files
written before that cutover: each logs/*.jsonl becomes logs/*.jsonl.enc — a
single Fernet token over the file's contents, using the same
SAFI_ENCRYPTION_KEY (MultiFernet: first key encrypts, all keys decrypt) as
the application's at-rest columns — and the plaintext original is removed.
The run is recorded in org_compliance_log (org NULL: files mix orgs).

Usage:
  venv/bin/python scripts/encrypt_jsonl_logs.py            # encrypt all
  venv/bin/python scripts/encrypt_jsonl_logs.py --dry-run
  venv/bin/python scripts/encrypt_jsonl_logs.py --decrypt logs/foo-2026-06-01.jsonl.enc
      # prints the plaintext JSONL to stdout (for historical lookups)

Idempotent: already-encrypted files are skipped; a crash between write and
unlink leaves both files, and the re-run just removes the plaintext.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from safi_app.config import Config
from safi_app.persistence import crypto
from safi_app.persistence import database as db

ACTOR = "system:encrypt_jsonl_logs"


def log_dir() -> Path:
    return Path(__file__).resolve().parent.parent / Config.LOG_DIR


def encrypt_all(dry_run: bool) -> int:
    if not crypto.is_enabled():
        print("SAFI_ENCRYPTION_KEY is not set — refusing to run (nothing to encrypt with).")
        return 2
    d = log_dir()
    if not d.is_dir():
        print(f"log dir {d} does not exist — nothing to do")
        return 0
    files = sorted(d.rglob("*.jsonl"))
    if not files:
        print("no plaintext .jsonl files found — nothing to do")
        return 0
    total_bytes = 0
    done = 0
    for f in files:
        enc_path = f.with_suffix(f.suffix + ".enc")
        size = f.stat().st_size
        total_bytes += size
        if dry_run:
            print(f"would encrypt {f.name} ({size} bytes) -> {enc_path.name}")
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        token = crypto.encrypt_value(text) or ""
        if not token.startswith(crypto.FERNET_PREFIX):
            print(f"REFUSED: encryption produced no token for {f.name} — aborting before any deletion")
            return 2
        enc_path.write_text(token, encoding="ascii")
        # Verify the round trip before destroying the plaintext.
        if crypto.decrypt_value(enc_path.read_text(encoding="ascii")) != text:
            print(f"REFUSED: round-trip verification failed for {f.name} — plaintext kept")
            return 2
        f.unlink()
        done += 1
        print(f"encrypted {f.name} ({size} bytes)")
    if dry_run:
        print(f"dry run: {len(files)} files, {total_bytes} bytes")
        return 0
    db.append_compliance_log(None, "log_files_encrypted", ACTOR, {
        "files": done, "bytes": total_bytes,
        "note": "legacy plaintext JSONL governance logs Fernet-encrypted in place",
    })
    print(f"done: {done} files encrypted, evidence logged")
    return 0


def decrypt_one(path: str) -> int:
    p = Path(path)
    if not p.is_file():
        print(f"{p} not found", file=sys.stderr)
        return 2
    plain = crypto.decrypt_value(p.read_text(encoding="ascii"))
    sys.stdout.write(plain)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--decrypt", metavar="FILE", help="print a .jsonl.enc file's plaintext to stdout")
    args = ap.parse_args()
    if args.decrypt:
        sys.exit(decrypt_one(args.decrypt))
    sys.exit(encrypt_all(args.dry_run))


if __name__ == "__main__":
    main()
