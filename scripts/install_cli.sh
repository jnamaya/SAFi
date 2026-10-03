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

# 4. Create launcher script
echo "Writing launcher to ${BIN_DIR}/safi..."
cat << EOF > "${BIN_DIR}/safi"
#!/usr/bin/env bash
export PYTHONPATH="${INSTALL_DIR}:\${PYTHONPATH}"
exec "${TARGET_PYTHON}" -m safi_cli.main "\$@"
EOF

chmod +x "${BIN_DIR}/safi"

echo ""
echo "=========================================================="
echo "✓ SAFi CLI installed successfully to ${BIN_DIR}/safi"
echo "=========================================================="
echo ""
echo "Quick Setup:"
echo "  1. Point to your remote SAFi server:"
echo "     safi --set-url https://safi.yourdomain.com"
echo ""
echo "  2. Save your API key:"
echo "     safi --set-key sk-safi-..."
echo ""
echo "  3. Start using SAFi:"
echo "     safi"
echo ""
