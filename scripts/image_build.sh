#!/usr/bin/env bash
# One-command local image build + defaults smoke check.
#
#   scripts/image_build.sh [tag]      # default tag: safi:v1.5.0
#
# .dockerignore keeps deploy/, mcp/ and .safi/ out of the context, so this
# ships tens of MB to the daemon no matter how large the ISO workspace is.
# The deps stage (requirements.txt/requirements.lock) is layer-cached, so a
# source-only change rebuilds in seconds. No docker-compose plugin needed.
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="${1:-safi:v1.5.0}"

time docker build -t "$TAG" .

# Smoke check: the fresh image must come up with the intended agent defaults
# (no .env in the image, no env passed, so pure code defaults print).
# NOTE: the -c payload below is single-quoted and column-0 on every line —
# any leading indentation would be a Python IndentationError at smoke time.
docker run --rm --entrypoint /opt/venv/bin/python3 "$TAG" -c '
from safi_app.config import Config
assert Config.DEFAULT_PROFILE == "software_engineer", Config.DEFAULT_PROFILE
assert Config.BUILTIN_AGENTS == ["software_engineer", "sysadmin", "tutor"], Config.BUILTIN_AGENTS
print("DEFAULT_PROFILE =", Config.DEFAULT_PROFILE)
print("BUILTIN_AGENTS  =", ",".join(Config.BUILTIN_AGENTS))'
echo "OK: $TAG"
