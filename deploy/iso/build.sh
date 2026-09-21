#!/bin/bash
# Builds the SAFi Appliance ISO.
#
#   ./build.sh                 # bookworm, amd64, SAFI_REF=v1.4.1
#   SAFI_REF=v1.4 ./build.sh   # build another release
#   SAFI_DIST=trixie ./build.sh
#
# Requires live-build on a Debian host (or in a VM/container):
#   apt install live-build debootstrap
#
# Run from this directory. Produces safi-appliance-<ref>-<arch>.iso in ./.
set -euo pipefail

cd "$(dirname "$0")"

for cmd in lb git; do
    command -v "$cmd" >/dev/null 2>&1 || {
        echo "missing '$cmd' — install live-build and friends: apt install live-build debootstrap git" >&2
        exit 1
    }
done
id -u | grep -q '^0$' || echo "note: building as non-root — live-build usually wants root (run with sudo)" >&2

SAFI_REF="${SAFI_REF:-v1.4.1}"
SAFI_ARCH="${SAFI_ARCH:-amd64}"

echo "==> SAFi Appliance build"
echo "    ref:    $SAFI_REF"
echo "    arch:   $SAFI_ARCH"
echo "    dist:   ${SAFI_DIST:-bookworm}"

lb clean --purge 2>/dev/null || true
lb config
lb build

OUT="safi-appliance-$SAFI_REF-$SAFI_ARCH.iso"
if [ -f live-image-"$SAFI_ARCH".hybrid.iso ]; then
    mv -f live-image-"$SAFI_ARCH".hybrid.iso "$OUT"
else
    built=$(ls -1t *.iso 2>/dev/null | head -1 || true)
    [ -n "$built" ] && { echo "renaming $built -> $OUT" >&2; mv -f "$built" "$OUT"; }
fi

echo "==> done: $(ls -lh "$OUT" 2>/dev/null | awk '{print $5}' | tr -d '\n'), file: ./$OUT"
echo "    boot in a VM: qemu-system-x86_64 -m 4096 -smp 2 -cdrom $OUT -boot d"