#!/bin/bash
# Automatically unblocks rfkill, associates wireless interfaces with Amaya, and acquires DHCP.
set -u

WPA_CONF="/etc/wpa_supplicant/wpa_supplicant.conf"
[ -f "$WPA_CONF" ] || exit 0

# Unblock any hardware/software radio locks
command -v rfkill >/dev/null 2>&1 && {
    rfkill unblock wifi 2>/dev/null || true
    rfkill unblock all 2>/dev/null || true
    sleep 1
}

# Discover all wireless network interfaces
find_wireless() {
    for iface_path in /sys/class/net/*; do
        [ -e "$iface_path" ] || continue
        local dev
        dev=$(basename "$iface_path")
        [ "$dev" = "lo" ] && continue
        if [ -d "$iface_path/wireless" ] || [ -d "$iface_path/phy80211" ] || echo "$dev" | grep -qE '^wl'; then
            echo "$dev"
        fi
    done
}

NICS=$(find_wireless)
if [ -z "$NICS" ]; then
    echo "safi-wifi: no wireless interfaces detected."
    exit 0
fi

for nic in $NICS; do
    echo "safi-wifi: initializing wireless interface $nic..."
    ip link set "$nic" up 2>/dev/null || true
    sleep 1

    mkdir -p /var/run/wpa_supplicant
    rm -f "/var/run/wpa_supplicant/$nic"

    # Start wpa_supplicant if not already running for this interface
    if ! pgrep -f "wpa_supplicant.*-i[[:space:]]*$nic" >/dev/null; then
        echo "safi-wifi: starting wpa_supplicant on $nic..."
        wpa_supplicant -B -i "$nic" -c "$WPA_CONF" -D nl80211,wext 2>/dev/null || true
    fi

    # Wait up to 15 seconds for association / 4-way handshake completion
    echo "safi-wifi: waiting for WPA connection on $nic..."
    for i in $(seq 1 15); do
        state=$(wpa_cli -i "$nic" status 2>/dev/null | grep '^wpa_state=' | cut -d= -f2 || true)
        if [ "$state" = "COMPLETED" ]; then
            echo "safi-wifi: $nic associated successfully (state=COMPLETED)."
            break
        fi
        sleep 1
    done

    # Request DHCP lease if no global IPv4 address is assigned yet
    if ! ip -4 -o addr show dev "$nic" scope global | grep -q .; then
        echo "safi-wifi: requesting DHCP lease on $nic..."
        dhclient -4 -v "$nic" 2>/dev/null || dhclient -4 "$nic" 2>/dev/null || true
        for j in $(seq 1 5); do
            if ip -4 -o addr show dev "$nic" scope global | grep -q .; then
                echo "safi-wifi: IP lease acquired on $nic."
                break
            fi
            sleep 1
        done
    fi
done

exit 0
