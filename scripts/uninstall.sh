#!/usr/bin/env bash
set -e

PURGE=0
for arg in "$@"; do
    case "$arg" in
        --purge|-p) PURGE=1 ;;
    esac
done
if [ "${SAFI_PURGE:-0}" = "1" ]; then
    PURGE=1
fi

echo "=== SAFi CLI Uninstaller ==="

# 1. Remove binary launchers from ~/.local/bin
echo "Removing binary launchers from ~/.local/bin..."
rm -f "${HOME}/.local/bin/safi-cli" \
      "${HOME}/.local/bin/saficli" \
      "${HOME}/.local/bin/sys-exec" \
      "${HOME}/.local/bin/safi-setup-key"

# 2. Remove system-wide symlinks if present
if [ -w "/usr/local/bin" ]; then
    rm -f /usr/local/bin/safi-cli /usr/local/bin/saficli /usr/local/bin/sys-exec /usr/local/bin/safi-setup-key 2>/dev/null || true
elif command -v sudo &>/dev/null && sudo -n true 2>/dev/null; then
    sudo -n rm -f /usr/local/bin/safi-cli /usr/local/bin/saficli /usr/local/bin/sys-exec /usr/local/bin/safi-setup-key 2>/dev/null || true
fi

# 3. Remove application package and venv
echo "Removing application package from ~/.local/share/safi-cli..."
rm -rf "${HOME}/.local/share/safi-cli"

# 4. Remove config and scratchpad directories ONLY when --purge / SAFI_PURGE=1 is set
if [ "$PURGE" -eq 1 ]; then
    echo "Purging SAFi configuration and inventory (~/.config/safi, ~/.safi)..."
    rm -rf "${HOME}/.config/safi"
    rm -rf "${HOME}/.safi"
    [ -d "${HOME}/.config" ] && [ -z "$(ls -A "${HOME}/.config" 2>/dev/null)" ] && rmdir "${HOME}/.config" 2>/dev/null || true
else
    echo "Preserving user configuration and inventory in ~/.config/safi (pass --purge or SAFI_PURGE=1 to remove)."
fi

# Clean up ~/.local/bin and ~/.local if empty
[ -d "${HOME}/.local/bin" ] && [ -z "$(ls -A "${HOME}/.local/bin" 2>/dev/null)" ] && rmdir "${HOME}/.local/bin" 2>/dev/null || true
[ -d "${HOME}/.local" ] && [ -z "$(ls -A "${HOME}/.local" 2>/dev/null)" ] && rmdir "${HOME}/.local" 2>/dev/null || true

# 5. Remove Windows host bridges (and folders only on --purge) if running in WSL
if grep -qi "microsoft" /proc/version 2>/dev/null && command -v cmd.exe &>/dev/null; then
    echo "Cleaning up Windows host bridges..."
    WIN_APPS_RAW=$(cmd.exe /c "echo %LOCALAPPDATA%\Microsoft\WindowsApps" 2>/dev/null | tr -d '\r')
    if [ -n "$WIN_APPS_RAW" ] && command -v wslpath &>/dev/null; then
        WIN_APPS_DIR=$(wslpath "$WIN_APPS_RAW" 2>/dev/null || true)
        if [ -n "$WIN_APPS_DIR" ] && [ -d "$WIN_APPS_DIR" ]; then
            rm -f "${WIN_APPS_DIR}/safi-cli.cmd" "${WIN_APPS_DIR}/saficli.cmd" "${WIN_APPS_DIR}/sys-exec.cmd" "${WIN_APPS_DIR}/safi-setup-key.cmd"
        fi
    fi

    WIN_PROFILE_RAW=$(cmd.exe /c "echo %USERPROFILE%" 2>/dev/null | tr -d '\r')
    if [ -n "$WIN_PROFILE_RAW" ] && command -v wslpath &>/dev/null; then
        WIN_PROFILE_DIR=$(wslpath "$WIN_PROFILE_RAW" 2>/dev/null || true)
        if [ -n "$WIN_PROFILE_DIR" ] && [ -d "$WIN_PROFILE_DIR" ]; then
            rm -f "${WIN_PROFILE_DIR}/.local/bin/safi-cli.cmd" \
                  "${WIN_PROFILE_DIR}/.local/bin/saficli.cmd" \
                  "${WIN_PROFILE_DIR}/.local/bin/sys-exec.cmd" \
                  "${WIN_PROFILE_DIR}/.local/bin/safi-setup-key.cmd"
            if [ "$PURGE" -eq 1 ]; then
                rm -rf "${WIN_PROFILE_DIR}/.safi"
                rm -rf "${WIN_PROFILE_DIR}/.config/safi"
                [ -d "${WIN_PROFILE_DIR}/.config" ] && [ -z "$(ls -A "${WIN_PROFILE_DIR}/.config" 2>/dev/null)" ] && rmdir "${WIN_PROFILE_DIR}/.config" 2>/dev/null || true
            fi
            [ -d "${WIN_PROFILE_DIR}/.local/bin" ] && [ -z "$(ls -A "${WIN_PROFILE_DIR}/.local/bin" 2>/dev/null)" ] && rmdir "${WIN_PROFILE_DIR}/.local/bin" 2>/dev/null || true
            [ -d "${WIN_PROFILE_DIR}/.local" ] && [ -z "$(ls -A "${WIN_PROFILE_DIR}/.local" 2>/dev/null)" ] && rmdir "${WIN_PROFILE_DIR}/.local" 2>/dev/null || true
        fi
    fi
fi

if [ "$PURGE" -eq 1 ]; then
    echo "✓ SAFi CLI and all configuration (.config/safi, .safi) have been completely removed."
else
    echo "✓ SAFi CLI uninstalled. Your configuration and inventory.json were preserved in ~/.config/safi."
fi
