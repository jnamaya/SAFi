#!/bin/bash
# Builds the SAFi Appliance ISO.
#
#   ./build.sh                 # bookworm, amd64, SAFI_REF=v1.4.1
#   SAFI_REF=v1.4 ./build.sh   # build another release
#   SAFI_DIST=trixie ./build.sh
#
# Private (unpublished) builds:
#   ./stage-local-release.sh [REF]  # stage a LOCAL tag clone, bump SAFI_REF
#   ./build.sh                      # SAFI_LOCAL_SRC=1 keeps the stage
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

# The release default lives in auto/config (the single version source), so the
# ISO filename and label agree with what stage-local-release.sh bakes in.
SAFI_REF="${SAFI_REF:-$(sed -n 's/^SAFI_REF="\${SAFI_REF:-\(.*\)}"/\1/p' auto/config)}"
SAFI_ARCH="${SAFI_ARCH:-amd64}"

echo "==> SAFi Appliance build"
echo "    ref:    $SAFI_REF"
echo "    arch:   $SAFI_ARCH"
echo "    dist:   ${SAFI_DIST:-bookworm}"

if ! lb clean --all; then
    echo "live-build cleanup failed; refusing to reuse stale installer artifacts" >&2
    exit 1
fi

# Purge the installer component cache. LB_CACHE_PACKAGES=true makes
# `lb clean --purge` leave the downloaded -di module udebs in place, so
# successive Debian point releases (e.g. 6.1.0-47 / -50) accumulate and mix
# with the live rootfs kernel (-53). A mismatched installer/live kernel makes
# live-installer copy an inconsistent root and grub-pc fails to install into
# /target. Force a fresh, single-version installer download.
rm -rf cache/installer_debian-installer cache/packages.installer_debian-installer.udeb

# A stale staged local-release snapshot (stage-local-release.sh) must never
# leak into a normal remote build, or the ISO would silently ship old code.
# Purge it unless the private-build flow re-requests it explicitly.
if [ -d config/includes.chroot/var/cache/safi-src ] && [ "${SAFI_LOCAL_SRC:-0}" != 1 ]; then
    echo "note: purging stale staged source (set SAFI_LOCAL_SRC=1 to keep it)"
    rm -rf config/includes.chroot/var/cache/safi-src
fi

lb config
lb build

# live-installer is loaded from the ISO's udeb pool at runtime (it is NOT
# installed into initrd.gz). Verify the live-build binary-stage artifacts.
if ! grep -qx 'live-installer' binary/.disk/udeb_include \
    || ! find binary/pool-udeb -type f -name 'live-installer_*.udeb' -print -quit \
       | grep -q .; then
    echo "live-installer udeb is missing from the ISO udeb pool" >&2
    exit 1
fi

# The d-i kernel MUST match the live-system kernel or the live install produces
# an unbootable target. Fail loudly rather than ship a mixed-kernel ISO.
DI_K="$(gzip -dc binary/install/initrd.gz 2>/dev/null | cpio -t 2>/dev/null \
        | grep -oE 'lib/modules/6\.[0-9]+\.[0-9]+-[0-9]+-amd64' | sort -u | sed -E 's#lib/modules/##')"
LIVE_K="$(ls binary/live/vmlinuz-* 2>/dev/null | sed -E 's#.*/vmlinuz-##' | sort -u)"
if [ -z "$DI_K" ] || [ "$DI_K" != "$LIVE_K" ]; then
    echo "installer kernel ($DI_K) does not match live-system kernel ($LIVE_K)" >&2
    exit 1
fi

OUT="safi-appliance-$SAFI_REF-$SAFI_ARCH.iso"
if [ -f live-image-"$SAFI_ARCH".hybrid.iso ]; then
    mv -f live-image-"$SAFI_ARCH".hybrid.iso "$OUT"
else
    built=$(ls -1t *.iso 2>/dev/null | head -1 || true)
    [ -n "$built" ] && { echo "renaming $built -> $OUT" >&2; mv -f "$built" "$OUT"; }
fi

echo "==> done: $(ls -lh "$OUT" 2>/dev/null | awk '{print $5}' | tr -d '\n'), file: ./$OUT"
echo "    boot in a VM: qemu-system-x86_64 -m 4096 -smp 2 -cdrom $OUT -boot d"
