#!/usr/bin/env bash
set -e

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

# 4. Remove config and scratchpad directories
echo "Removing SAFi configuration and state..."
rm -rf "${HOME}/.config/safi"
rm -rf "${HOME}/.safi"

# Clean up ~/.config if empty
[ -d "${HOME}/.config" ] && [ -z "$(ls -A "${HOME}/.config" 2>/dev/null)" ] && rmdir "${HOME}/.config" 2>/dev/null || true
# Clean up ~/.local/bin if empty
[ -d "${HOME}/.local/bin" ] && [ -z "$(ls -A "${HOME}/.local/bin" 2>/dev/null)" ] && rmdir "${HOME}/.local/bin" 2>/dev/null || true
# Clean up ~/.local if empty
[ -d "${HOME}/.local" ] && [ -z "$(ls -A "${HOME}/.local" 2>/dev/null)" ] && rmdir "${HOME}/.local" 2>/dev/null || true

# 5. Remove Windows host bridges and folders if running in WSL
if grep -qi "microsoft" /proc/version 2>/dev/null && command -v cmd.exe &>/dev/null; then
    echo "Cleaning up Windows host directories and bridges..."
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
            rm -rf "${WIN_PROFILE_DIR}/.safi"
            rm -rf "${WIN_PROFILE_DIR}/.config/safi"
            [ -d "${WIN_PROFILE_DIR}/.config" ] && [ -z "$(ls -A "${WIN_PROFILE_DIR}/.config" 2>/dev/null)" ] && rmdir "${WIN_PROFILE_DIR}/.config" 2>/dev/null || true
            [ -d "${WIN_PROFILE_DIR}/.local/bin" ] && [ -z "$(ls -A "${WIN_PROFILE_DIR}/.local/bin" 2>/dev/null)" ] && rmdir "${WIN_PROFILE_DIR}/.local/bin" 2>/dev/null || true
            [ -d "${WIN_PROFILE_DIR}/.local" ] && [ -z "$(ls -A "${WIN_PROFILE_DIR}/.local" 2>/dev/null)" ] && rmdir "${WIN_PROFILE_DIR}/.local" 2>/dev/null || true
        fi
    fi
fi

echo "✓ SAFi CLI and all configuration (.config, .local, .safi) have been completely removed."
