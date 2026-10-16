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
    echo "Downloading safi_cli package from repository..."
    rm -rf "${INSTALL_DIR}/safi_cli"
    TMP_DIR=$(mktemp -d)
    git clone --depth 1 https://github.com/jnamaya/SAFi.git "${TMP_DIR}/safi-repo"
    cp -r "${TMP_DIR}/safi-repo/safi_cli" "${INSTALL_DIR}/"
    rm -rf "${TMP_DIR}"
fi

# 3. Setup Python runtime (try venv first, fallback to user python)
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
    # Venv was not created (e.g. Debian/Ubuntu missing python3-venv), check if rich/requests exist
    if "${PYTHON_BIN}" -c "import requests, rich" 2>/dev/null; then
        echo "Using existing Python environment (requests and rich already present)."
        TARGET_PYTHON="${PYTHON_BIN}"
    else
        echo "Attempting to install 'requests' and 'rich'..."
        if "${PYTHON_BIN}" -m pip install --user requests rich 2>/dev/null || "${PYTHON_BIN}" -m pip install --user --break-system-packages requests rich 2>/dev/null; then
            TARGET_PYTHON="${PYTHON_BIN}"
        else
            echo "Warning: could not auto-install requests and rich."
            echo "Please run: sudo apt install python3-venv (or pip install requests rich)"
        fi
    fi
fi

# 4. Check & Install Sysadmin CLI dependencies (openssh, sshpass, nmap, jq)
echo "Checking sysadmin operational tooling..."
SYS_PKGS=()
for tool in ssh sshpass nmap jq; do
    if ! command -v "$tool" &>/dev/null; then
        SYS_PKGS+=("$tool")
    fi
done

if [ ${#SYS_PKGS[@]} -gt 0 ]; then
    echo "Optional sysadmin utilities missing: ${SYS_PKGS[*]}"
    if command -v apt-get &>/dev/null && [ "$(id -u)" -eq 0 ]; then
        apt-get update -qq && apt-get install -y -qq openssh-client sshpass nmap jq || true
    elif command -v apt-get &>/dev/null && command -v sudo &>/dev/null; then
        echo "Attempting to install missing sysadmin tools via sudo apt-get..."
        sudo apt-get update -qq && sudo apt-get install -y -qq openssh-client sshpass nmap jq || echo "Notice: Could not auto-install via sudo. Please install manually: sudo apt install ${SYS_PKGS[*]}"
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

# 7. Scaffold inventory template if missing
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
echo "✓ SAFi CLI & sys-exec installed successfully to ${BIN_DIR}"
echo "=========================================================="
echo ""
echo "Quick Setup:"
echo "  1. Point to your remote SAFi server:"
echo "     safi --set-url https://safi.yourdomain.com"
echo ""
echo "  2. Save your API key:"
echo "     safi --set-key sk-safi-..."
echo ""
echo "  3. Manage servers via ~/.config/safi/inventory.json:"
echo "     sys-exec --list"
echo ""
echo "  4. Start using the Sysadmin Agent:"
echo "     safi --agent sysadmin"
echo ""
