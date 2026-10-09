#!/bin/sh
# safi-gpu-tune — keep the integrated AMD GPU productive on every boot.
#
# Three knobs, all idempotent and all safe to re-apply:
#
#  1. Lock GPU clocks high so RADV does not down-throttle mid-generation.
#  2. Widen the TTM GTT pool. By default amdgpu caps GPU-mappable memory at
#     50% of RAM; on an APU the Vulkan heap llama.cpp allocates IS this pool,
#     so a 64 GB Strix Halo would see only ~32 GiB of GPU memory without it.
#     We set ~88% of currently-visible RAM (the BIOS UMA carve-out is excluded
#     from /proc/meminfo, so a misconfigured box still lands on a sane value).
#  3. THP madvise (Debian default, re-asserted) to avoid allocation stalls as
#     the KV cache expands.
#
# Runs before safi-browser-setup.service so setup-time model fetch and the
# first llama-server boot see the widened pool. Errors degrade, never fail:
# a non-amdgpu box has no /dev/drm cards to tune and must boot regardless.
set -eu

# 1 + 3
for card in /sys/class/drm/card*/device; do
    [ -d "$card" ] || continue
    vendor=$(cat "$card/vendor" 2>/dev/null || true)
    [ "$vendor" = "0x1002" ] || continue
    echo "high" > "$card/power_dpm_force_performance_level" 2>/dev/null || true
done
echo "madvise" > /sys/kernel/mm/transparent_hugepage/enabled 2>/dev/null || true

# 2 — pages_limit is counted in base-page (4096 B) units. ~88% of RAM.
ram_kb=$(awk '/^MemTotal:/ { print $2 }' /proc/meminfo 2>/dev/null || echo 0)
if [ -n "$ram_kb" ] && [ "$ram_kb" -gt 0 ]; then
    pages=$(( ram_kb * 88 / 100 / 4 ))
    # Hard ceiling: ~120 GiB, the tuned value for the 128 GB EVO-X2.
    [ "$pages" -gt 31457280 ] && pages=31457280
    [ "$pages" -lt 1 ] && pages=1
    for param in /sys/module/ttm/parameters/pages_limit \
                 /sys/module/amdttm/parameters/pages_limit; do
        [ -w "$param" ] && echo "$pages" > "$param" 2>/dev/null || true
    done
fi

exit 0