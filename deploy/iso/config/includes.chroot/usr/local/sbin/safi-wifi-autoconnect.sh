#!/bin/bash
# Automatically unblocks rfkill, associates wireless interfaces with Amaya, and acquires DHCP.
set -u

WPA_CONF="/etc/wpa_supplicant/wpa_supplicant.conf"
[ -f "$WPA_CONF" ] || exit 0

command -v rfkill >/dev/null 2>&1 && {
    rfkill unblock wifi 2>/dev/null || true
    rfkill unblock all 2>/dev/null || true
}

for nic in $(ls /sys/class/net 2>/dev/null | grep -v '^lo$'); do
    if [ -d "/sys/class/net/$nic/wireless" ] || [ -d "/sys/class/net/$nic/phy80211" ] || echo "$nic" | grep -q '^wl'; then
        ip link set "$nic" up 2>/dev/null || true
        
        # Start wpa_supplicant if not already running for this interface
        if ! pgrep -f "wpa_supplicant.*-i[[:space:]]*$nic" >/dev/null; then
            wpa_supplicant -B -i "$nic" -c "$WPA_CONF" 2>/dev/null || true
        fi
        
        # If no IPv4 address is assigned yet, attempt dhclient
        if ! ip -4 -o addr show dev "$nic" scope global | grep -q .; then
            ifup "$nic" 2>/dev/null || dhclient -4 -q "$nic" 2>/dev/null || true
        fi
    fi
done
