#!/usr/bin/env bash
set -e

# SAFi CLI Standalone Installer
# Installs only the lightweight CLI client (No Docker, No Database required).

INSTALL_DIR="${HOME}/.local/share/safi-cli"
BIN_DIR="${HOME}/.local/bin"

echo "=== SAFi Governed Agent Interface — CLI Installer ==="


# 1. Check Python 3
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 is required but not installed." >&2
    exit 1
fi

PYTHON_BIN=$(command -v python3)
PYTHON_VERSION=$("${PYTHON_BIN}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Detected Python: ${PYTHON_VERSION} (${PYTHON_BIN})"

# 2. Prepare directories
mkdir -p "${INSTALL_DIR}"
mkdir -p "${BIN_DIR}"

# Determine source directory (if run from git clone or standalone)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"

if [ -d "${REPO_DIR}/safi_cli" ]; then
    echo "Installing safi_cli from local tree..."
    rm -rf "${INSTALL_DIR}/safi_cli"
    cp -r "${REPO_DIR}/safi_cli" "${INSTALL_DIR}/"
else
    SAFI_BRANCH="${SAFI_BRANCH:-dev}"
    echo "Downloading safi_cli package from repository (${SAFI_BRANCH} branch)..."
    rm -rf "${INSTALL_DIR}/safi_cli"
    TMP_DIR=$(mktemp -d)
    git clone --depth 1 --branch "${SAFI_BRANCH}" https://github.com/jnamaya/SAFi.git "${TMP_DIR}/safi-repo"
    cp -r "${TMP_DIR}/safi-repo/safi_cli" "${INSTALL_DIR}/"
    rm -rf "${TMP_DIR}"
fi

# 3. Check & Install system packages (python3-venv, sshpass, nmap, jq)
echo "Checking operational system packages..."
PKGS=()
for tool in ssh sshpass nmap jq; do
    if ! command -v "$tool" &>/dev/null; then
        PKGS+=("$tool")
    fi
done

if ! "${PYTHON_BIN}" -m venv --help &>/dev/null; then
    PKGS+=("python3-venv" "python3-pip")
fi

if [ ${#PKGS[@]} -gt 0 ]; then
    echo "Installing missing system utilities: ${PKGS[*]}..."
    if command -v apt-get &>/dev/null && [ "$(id -u)" -eq 0 ]; then
        apt-get update -qq && apt-get install -y -qq "${PKGS[@]}" || true
    elif command -v apt-get &>/dev/null && command -v sudo &>/dev/null; then
        sudo apt-get update -qq && sudo apt-get install -y -qq "${PKGS[@]}" || true
    fi
fi

# 4. Setup Python runtime (isolated venv preferred)
TARGET_PYTHON="${PYTHON_BIN}"
USE_VENV=0

if "${PYTHON_BIN}" -m venv "${INSTALL_DIR}/venv" 2>/dev/null; then
    if [ -f "${INSTALL_DIR}/venv/bin/pip" ]; then
        echo "Created isolated venv in ${INSTALL_DIR}/venv"
        "${INSTALL_DIR}/venv/bin/pip" install --quiet requests rich
        TARGET_PYTHON="${INSTALL_DIR}/venv/bin/python"
        USE_VENV=1
    fi
fi

if [ "${USE_VENV}" -eq 0 ]; then
    if "${PYTHON_BIN}" -c "import requests, rich" 2>/dev/null; then
        echo "Using existing Python environment (requests and rich already present)."
        TARGET_PYTHON="${PYTHON_BIN}"
    else
        echo "Attempting to install 'requests' and 'rich'..."
        if "${PYTHON_BIN}" -m pip install --user requests rich 2>/dev/null || "${PYTHON_BIN}" -m pip install --user --break-system-packages requests rich 2>/dev/null; then
            TARGET_PYTHON="${PYTHON_BIN}"
        else
            echo "Warning: could not auto-install requests and rich."
        fi
    fi
fi

# 5. Create launcher script
echo "Writing launcher to ${BIN_DIR}/safi..."
cat << EOF > "${BIN_DIR}/safi"
#!/usr/bin/env bash
export PYTHONPATH="${INSTALL_DIR}:\${PYTHONPATH}"
exec "${TARGET_PYTHON}" -m safi_cli.main "\$@"
EOF
chmod +x "${BIN_DIR}/safi"

# 6. Create sys-exec infrastructure runner
echo "Writing sys-exec runner to ${BIN_DIR}/sys-exec..."
cat << 'EOF' > "${BIN_DIR}/sys-exec"
#!/usr/bin/env bash
set -eo pipefail

CONFIG_DIR="${HOME}/.config/safi"
INVENTORY_FILE="${CONFIG_DIR}/inventory.json"

usage() {
    cat << 'HELP'
Usage:
  sys-exec --list                      List all managed inventory hosts
  sys-exec <target-alias> <command>    Execute command on the target host (SSH key authentication)

Examples:
  sys-exec --list
  sys-exec web-server "uptime; free -h"
  sys-exec db-cluster "systemctl status mariadb"
HELP
    exit 1
}

if [ $# -eq 0 ] || [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    usage
fi

if [ ! -f "$INVENTORY_FILE" ]; then
    echo "Error: Inventory file not found at $INVENTORY_FILE" >&2
    exit 1
fi

if [ "$1" = "--list" ] || [ "$1" = "-l" ]; then
    echo "Managed Infrastructure Inventory ($INVENTORY_FILE):"
    jq -r 'to_entries[] | "  - \(.key): \(.value.user // "(ssh-config)")@\(.value.host) (auth: \(.value.auth)) — \(.value.description // "")"' "$INVENTORY_FILE"
    exit 0
fi

if [ $# -lt 2 ]; then
    echo "Error: Missing command to execute." >&2
    usage
fi

TARGET="$1"
shift
CMD="$*"

TARGET_CONFIG=$(jq -r --arg t "$TARGET" '.[$t] // empty' "$INVENTORY_FILE")
if [ -z "$TARGET_CONFIG" ]; then
    echo "Error: Unknown host alias '$TARGET'. Available hosts:" >&2
    jq -r 'keys[] | "  - \(.)"' "$INVENTORY_FILE" >&2
    exit 1
fi

HOST=$(echo "$TARGET_CONFIG" | jq -r '.host')
# Strip leading 'ssh ' prefix if accidentally specified in host
HOST="${HOST#ssh }"

USER=$(echo "$TARGET_CONFIG" | jq -r '.user // empty')
PORT=$(echo "$TARGET_CONFIG" | jq -r '.port // empty')
AUTH=$(echo "$TARGET_CONFIG" | jq -r '.auth // "key"')

SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)
if [ -n "$PORT" ] && [ "$PORT" != "null" ]; then
    SSH_OPTS+=(-p "$PORT")
fi

if [ -n "$USER" ] && [ "$USER" != "null" ]; then
    DEST="${USER}@${HOST}"
else
    DEST="${HOST}"
fi

if [ "$AUTH" = "key" ] || [ "$AUTH" = "ssh" ] || [ "$AUTH" = "ssh_config" ]; then
    # Key-based / SSH-config execution
    ssh -o BatchMode=yes "${SSH_OPTS[@]}" "$DEST" "$CMD"
    exit $?
elif [ "$AUTH" = "password" ]; then
    echo "Error: Plain-text password storage has been disabled for security. Please configure SSH key-based authentication for '$TARGET' (e.g. ssh-copy-id)." >&2
    exit 1
else
    echo "Error: Unsupported auth method '$AUTH' for '$TARGET'. Please use SSH key-based authentication." >&2
    exit 1
fi
EOF
chmod +x "${BIN_DIR}/sys-exec"

# 7. Make safi and sys-exec universally available in system PATH
if [ -w "/usr/local/bin" ]; then
    ln -sf "${BIN_DIR}/safi" /usr/local/bin/safi 2>/dev/null || true
    ln -sf "${BIN_DIR}/sys-exec" /usr/local/bin/sys-exec 2>/dev/null || true
elif command -v sudo &>/dev/null; then
    sudo ln -sf "${BIN_DIR}/safi" /usr/local/bin/safi 2>/dev/null || true
    sudo ln -sf "${BIN_DIR}/sys-exec" /usr/local/bin/sys-exec 2>/dev/null || true
fi

# Fallback: persist ~/.local/bin in user shell profiles
if [[ ":$PATH:" != *":${BIN_DIR}:"* ]]; then
    if [ -f "${HOME}/.bashrc" ] && ! grep -q '\.local/bin' "${HOME}/.bashrc" 2>/dev/null; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "${HOME}/.bashrc"
    fi
    if [ -f "${HOME}/.profile" ] && ! grep -q '\.local/bin' "${HOME}/.profile" 2>/dev/null; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "${HOME}/.profile"
    fi
fi

# 8. WSL Windows Host Integration
# If running inside WSL, bridge safi to Windows so users can run 'safi' directly from Windows PowerShell / CMD
if grep -qi "microsoft" /proc/version 2>/dev/null && command -v cmd.exe &>/dev/null; then
    echo "Detected WSL environment — configuring Windows PowerShell & CMD integration..."
    WIN_APPS_RAW=$(cmd.exe /c "echo %LOCALAPPDATA%\Microsoft\WindowsApps" 2>/dev/null | tr -d '\r')
    if [ -n "$WIN_APPS_RAW" ] && command -v wslpath &>/dev/null; then
        WIN_APPS_DIR=$(wslpath "$WIN_APPS_RAW" 2>/dev/null || true)
        if [ -n "$WIN_APPS_DIR" ] && [ -d "$WIN_APPS_DIR" ]; then
            cat << 'EOF' > "${WIN_APPS_DIR}/safi.cmd"
@echo off
wsl.exe -e safi %*
exit /b %ERRORLEVEL%
EOF
            cat << 'EOF' > "${WIN_APPS_DIR}/sys-exec.cmd"
@echo off
wsl.exe -e sys-exec %*
exit /b %ERRORLEVEL%
EOF
            chmod +x "${WIN_APPS_DIR}/safi.cmd" "${WIN_APPS_DIR}/sys-exec.cmd" 2>/dev/null || true
            echo "✓ Created Windows bridge in ${WIN_APPS_RAW} (safi.cmd & sys-exec.cmd)"
        fi
    fi

    WIN_PROFILE_RAW=$(cmd.exe /c "echo %USERPROFILE%" 2>/dev/null | tr -d '\r')
    if [ -n "$WIN_PROFILE_RAW" ] && command -v wslpath &>/dev/null; then
        WIN_PROFILE_DIR=$(wslpath "$WIN_PROFILE_RAW" 2>/dev/null || true)
        if [ -n "$WIN_PROFILE_DIR" ] && [ -d "$WIN_PROFILE_DIR" ]; then
            mkdir -p "${WIN_PROFILE_DIR}/.local/bin"
            cat << 'EOF' > "${WIN_PROFILE_DIR}/.local/bin/safi.cmd"
@echo off
wsl.exe -e safi %*
exit /b %ERRORLEVEL%
EOF
            cat << 'EOF' > "${WIN_PROFILE_DIR}/.local/bin/sys-exec.cmd"
@echo off
wsl.exe -e sys-exec %*
exit /b %ERRORLEVEL%
EOF
            if command -v powershell.exe &>/dev/null; then
                powershell.exe -NoProfile -NonInteractive -Command "
                \$binDir = Join-Path \$env:USERPROFILE '.local\bin';
                \$userPath = [Environment]::GetEnvironmentVariable('Path', 'User');
                if (\$userPath -and \$userPath -notlike \"*\$binDir*\") {
                    [Environment]::SetEnvironmentVariable('Path', (\$userPath + ';' + \$binDir).Trim(';'), 'User')
                }
                " 2>/dev/null || true
            fi
        fi
    fi
fi

# 9. Scaffold inventory template if missing
CONFIG_DIR="${HOME}/.config/safi"
mkdir -p "${CONFIG_DIR}"

if [ ! -f "${CONFIG_DIR}/inventory.json" ]; then
    cat << 'EOF' > "${CONFIG_DIR}/inventory.json"
{
  "example-server": {
    "host": "192.168.1.100",
    "user": "admin",
    "port": 22,
    "auth": "key",
    "description": "Example target server"
  }
}
EOF
    echo "Created sample inventory at ${CONFIG_DIR}/inventory.json"
fi

echo ""
echo "=========================================================="
echo "✓ SAFi CLI installed successfully!"
echo "=========================================================="
echo ""
echo "To get started, simply run:"
echo "   safi"
echo ""
