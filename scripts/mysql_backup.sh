#!/usr/bin/env bash
# Nightly logical backup of the SAFi MySQL database (SEA 17a-4 evidence base).
#
# Dumps the `safi` schema with mysqldump --single-transaction (consistent
# InnoDB snapshot, no locks against the running app), gzips it into
# /var/backups/safi/, integrity-checks the result, and prunes dumps older
# than RETAIN_DAYS. The dump deliberately has no CREATE DATABASE/USE header
# so backup_verify.py can restore it into a scratch schema.
#
# Off-box copy: set SAFI_BACKUP_REMOTE in /var/www/safi/.env to any rsync
# destination (e.g. user@host:/path). Until it is set, every run logs a
# warning — a backup that only lives on the host it protects is not done.
#
# Runs as the `safi` user via safi-backup.timer. Exits non-zero on any
# failure so the systemd unit lands in a failed state.
set -euo pipefail
# Dumps are full plaintext DB snapshots; never expose them wider than the
# backup group. The timer and `safi backup` both run as the `safi` user, so
# files land 0600 safi:safi instead of 0644.
umask 077

ENV_FILE=/var/www/safi/.env
BACKUP_DIR=/var/backups/safi
RETAIN_DAYS=14
MIN_BYTES=5000  # a fresh-empty schema gzips to ~12 KB; much smaller means broken

env_get() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -1; }

DB_HOST=$(env_get DB_HOST)
DB_USER=$(env_get DB_USER)
DB_PASSWORD=$(env_get DB_PASSWORD)
DB_NAME=$(env_get DB_NAME)
: "${DB_HOST:=localhost}" "${DB_NAME:=safi}"
[ -n "$DB_USER" ] && [ -n "$DB_PASSWORD" ] || { echo "ERROR: DB_USER/DB_PASSWORD missing from $ENV_FILE" >&2; exit 1; }

CNF=$(mktemp)
trap 'rm -f "$CNF"' EXIT
chmod 600 "$CNF"
printf '[client]\nuser=%s\npassword="%s"\nhost=%s\n' "$DB_USER" "$DB_PASSWORD" "$DB_HOST" > "$CNF"

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT="$BACKUP_DIR/safi-$STAMP.sql.gz"

# --no-tablespaces: the safi DB user has no PROCESS privilege (MySQL 8).
# --set-gtid-purged=OFF is a MySQL-8-only option; the MariaDB mysqldump the
# appliance ships rejects it, so it is only added when the dump tool supports
# it. Both keep the dump restorable into the scratch verify schema.
GTID_ARGS=()
if mysqldump --help 2>/dev/null | grep -q 'set-gtid-purged'; then
    GTID_ARGS=(--set-gtid-purged=OFF)
fi

install -d "$BACKUP_DIR"  # the timer might be the first thing that ever runs
mysqldump --defaults-extra-file="$CNF" \
    --single-transaction --quick --triggers \
    --no-tablespaces "${GTID_ARGS[@]}" \
    "$DB_NAME" | gzip > "$OUT"

gzip -t "$OUT"
BYTES=$(stat -c%s "$OUT")
if [ "$BYTES" -lt "$MIN_BYTES" ]; then
    echo "ERROR: dump $OUT is only $BYTES bytes — refusing to trust it" >&2
    exit 1
fi
# Cheap structural guard on top of size: a valid safi dump always carries table
# DDL, even when the fresh-empty schema is small and the old multi-MB floor no
# longer applies. Catches a failed dump that still produced a plausible size.
if ! zgrep -Eqm1 'CREATE TABLE' "$OUT"; then
    echo "ERROR: dump $OUT contains no table DDL — refusing to trust it" >&2
    exit 1
fi

find "$BACKUP_DIR" -maxdepth 1 -name 'safi-*.sql.gz' -mtime +"$RETAIN_DAYS" -delete

REMOTE=$(env_get SAFI_BACKUP_REMOTE || true)
if [ -n "${REMOTE:-}" ]; then
    rsync -a "$OUT" "$REMOTE"
    echo "OK: $OUT ($BYTES bytes), copied off-box to $REMOTE"
else
    echo "WARNING: SAFI_BACKUP_REMOTE not set — $OUT exists only on this host"
fi
