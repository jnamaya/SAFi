#!/usr/bin/env bash
# Pen-test repro / regression smoke script (SAFi remediation P1-P8).
# Usage: ./scripts/security_smoke.sh [https://safi.selfalignmentframework.com]
# Exits non-zero on the first check that FAILS. Each check prints PASS/FAIL.
set -u
BASE="${1:-https://safi.selfalignmentframework.com}"
FAIL=0

check() { # name expected actual
  if [ "$2" = "$3" ]; then echo "PASS: $1 ($3)"; else echo "FAIL: $1 (expected $2, got $3)"; FAIL=1; fi
}

code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

# P1/P2: login oracle collapsed + rate limited (10 bad logins -> 429, uniform 401 before that)
last=""
for i in $(seq 1 10); do
  last=$(code -X POST "$BASE/api/login" -H 'Content-Type: application/json' \
    -d '{"username":"nosuchuser-zzz","password":"wrong"}')
done
check "P1/P2 login rate limit (10th bad login)" 429 "$last"

# P3: no-key direct hit on public process_prompt -> 401 (proxied chatbots still work)
check "P3 internal-key enforcement" 401 "$(code -X POST "$BASE/api/public/process_prompt" \
  -H 'Content-Type: application/json' \
  -d '{"conversation_id":"11111111-1111-1111-1111-111111111111","message":"ping"}')"

# P4: /preview/ requires auth (fail2ban deployed server-side; from a disposable IP,
# 10 rapid bad passwords should get banned at the firewall)
check "P4 preview requires auth" 401 "$(code "$BASE/preview/")"

# P5: /api/me must not leak role internals
LEAK=$(curl -s "$BASE/api/me" | grep -ciE 'worldview|will_rules|tools|@demo\.local' || true)
check "P5 /api/me payload trimmed (0 leaks)" 0 "$LEAK"

# P6: CSP has no unsafe-inline in script-src
CSP=$(curl -sI "$BASE/" | grep -i '^content-security-policy:' || true)
if echo "$CSP" | grep -q "script-src[^;]*unsafe-inline"; then
  echo "FAIL: P6 CSP script-src still has unsafe-inline"; FAIL=1
else echo "PASS: P6 CSP script-src free of unsafe-inline"; fi

# P7: /api/messages returns deliberate 404, not 503
check "P7 /api/messages deliberate 404" 404 "$(code "$BASE/api/messages")"

# P8: HTTP -> HTTPS 301; no DHE ciphers; security.txt published
check "P8 HTTP->HTTPS 301" 301 "$(code "http://${BASE#https://}/")"
if nmap --script ssl-enum-ciphers -p 443 "${BASE#https://}" 2>/dev/null | grep -q 'DHE'; then
  echo "FAIL: P8 DHE ciphers still offered"; FAIL=1
else echo "PASS: P8 no DHE ciphers (or nmap unavailable — run manually)"; fi
check "P8 security.txt" 200 "$(code "$BASE/.well-known/security.txt")"

exit $FAIL
