#!/usr/bin/env bash
set -eo pipefail

CONFIG_DIR="${HOME}/.config/safi"
INVENTORY_FILE="${CONFIG_DIR}/inventory.json"
DEFAULT_KEY="${HOME}/.ssh/id_ed25519"
PUB_KEY="${DEFAULT_KEY}.pub"

usage() {
    cat << 'HELP'
Usage:
  safi setup-key <target-alias | user@host | host> [options]
  safi-setup-key <target-alias | user@host | host> [options]

Arguments:
  target-alias       Host alias defined in ~/.config/safi/inventory.json (e.g. local-VM, win-server)
  user@host          Direct target user and host/IP

Options:
  --port, -p <port>  SSH port (default: 22 or port from inventory)
  --user, -u <user>  Remote user (default: current user or user from inventory)
  --win, --windows   Force Windows OpenSSH setup (icacls / administrators_authorized_keys)
  --linux            Force Linux OpenSSH setup (ssh-copy-id)
  -h, --help         Show this help message

Examples:
  safi setup-key local-VM
  safi setup-key win-server
  safi setup-key nelson@192.168.1.218
HELP
    exit "${1:-1}"
}

if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    usage 0
fi

if [ $# -eq 0 ]; then
    usage 1
fi

TARGET="$1"
shift

PORT_OVERRIDE=""
USER_OVERRIDE=""
FORCE_OS=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -p|--port)
            PORT_OVERRIDE="$2"
            shift 2
            ;;
        -u|--user)
            USER_OVERRIDE="$2"
            shift 2
            ;;
        --win|--windows)
            FORCE_OS="windows"
            shift
            ;;
        --linux)
            FORCE_OS="linux"
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            ;;
    esac
done

# 1. Ensure local SSH key exists
if [ ! -f "$PUB_KEY" ]; then
    echo "No Ed25519 SSH key found at $PUB_KEY."
    echo "Generating new Ed25519 key pair..."
    mkdir -p "${HOME}/.ssh"
    chmod 700 "${HOME}/.ssh"
    ssh-keygen -t ed25519 -N "" -f "$DEFAULT_KEY" -C "safi-agent@$(hostname)"
    echo "✓ Created $DEFAULT_KEY and $PUB_KEY"
fi

KEY_CONTENT=$(cat "$PUB_KEY" | tr -d '\r\n')
if [ -z "$KEY_CONTENT" ]; then
    echo "Error: Public key $PUB_KEY is empty." >&2
    exit 1
fi

echo "=== SAFi SSH Key Deployment ==="
echo "Local Public Key: $PUB_KEY ($(ssh-keygen -lf "$PUB_KEY" | awk '{print $2}'))"

# 2. Resolve target from inventory.json or direct argument
HOST=""
USER=""
PORT="22"
OS_TYPE=""
IS_INVENTORY=0

if [ -f "$INVENTORY_FILE" ] && command -v jq &>/dev/null; then
    TARGET_CONFIG=$(jq -r --arg t "$TARGET" '.[$t] // empty' "$INVENTORY_FILE" 2>/dev/null || true)
    if [ -n "$TARGET_CONFIG" ]; then
        IS_INVENTORY=1
        HOST=$(echo "$TARGET_CONFIG" | jq -r '.host // empty')
        HOST="${HOST#ssh }"
        USER=$(echo "$TARGET_CONFIG" | jq -r '.user // empty')
        PORT=$(echo "$TARGET_CONFIG" | jq -r '.port // 22')
        DESC=$(echo "$TARGET_CONFIG" | jq -r '.description // empty')
        OS_TYPE=$(echo "$TARGET_CONFIG" | jq -r '.os // empty')

        if [ -z "$OS_TYPE" ]; then
            if [[ "${DESC,,}" == *"windows"* ]] || [[ "${TARGET,,}" == *"win"* ]]; then
                OS_TYPE="windows"
            else
                OS_TYPE="linux"
            fi
        fi
        echo "Resolved from SAFi Inventory: target '$TARGET' -> ${USER}@${HOST}:${PORT} (${OS_TYPE})"
    fi
fi

if [ -z "$HOST" ]; then
    # Direct target argument (e.g., user@host or host)
    if [[ "$TARGET" == *"@"* ]]; then
        USER="${TARGET%%@*}"
        HOST="${TARGET#*@}"
    else
        USER="${USER_OVERRIDE:-$USER}"
        HOST="$TARGET"
    fi
    OS_TYPE="linux"
fi

# Apply overrides
if [ -n "$USER_OVERRIDE" ]; then USER="$USER_OVERRIDE"; fi
if [ -n "$PORT_OVERRIDE" ]; then PORT="$PORT_OVERRIDE"; fi
if [ -n "$FORCE_OS" ]; then OS_TYPE="$FORCE_OS"; fi
if [ -z "$USER" ]; then USER="$LOGNAME"; fi
if [ -z "$PORT" ] || [ "$PORT" = "null" ]; then PORT="22"; fi

echo "Deploying key to: ${USER}@${HOST} (port ${PORT}, os: ${OS_TYPE})"

# 3. Check if key is already active
echo -n "Checking existing passwordless connectivity... "
if ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=4 -p "$PORT" "${USER}@${HOST}" "echo OK" &>/dev/null; then
    echo "ALREADY CONFIGURED ✓"
    echo "SSH key authentication is already working for ${USER}@${HOST}."
    if [ "$IS_INVENTORY" -eq 1 ]; then
        echo "You can run commands using: sys-exec $TARGET <command>"
    fi
    exit 0
fi
echo "needs installation."

# 4. Deploy Key based on OS
SSH_PORT_OPT=(-p "$PORT")

if [ "$OS_TYPE" = "windows" ]; then
    echo ""
    echo "Configuring Windows OpenSSH Server..."
    echo "Windows OpenSSH requires strict NTFS permissions (ACLs) via icacls."
    echo "You will be prompted for ${USER}@${HOST}'s Windows password once."
    echo ""

    # PowerShell command to set up authorized_keys / administrators_authorized_keys with strict ACLs
    PS_DEPLOY=$(cat << 'PSEOF'
$ErrorActionPreference = 'Stop'
$key = '__KEY_PLACEHOLDER__'
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$userLower = $env:USERNAME.ToLower()

if ($isAdmin -or $userLower -eq 'administrator') {
    $adminDir = "$env:ProgramData\ssh"
    if (!(Test-Path $adminDir)) { New-Item -ItemType Directory -Force -Path $adminDir | Out-Null }
    $adminFile = "$adminDir\administrators_authorized_keys"
    
    # Read existing without duplicates
    $existing = if (Test-Path $adminFile) { Get-Content -Raw $adminFile } else { "" }
    if ($existing -notmatch [regex]::Escape($key.Trim())) {
        Add-Content -Force -Path $adminFile -Value $key.Trim()
    }
    
    # Set strict ACL: inheritance removed, only SYSTEM and Administrators allowed
    & icacls.exe $adminFile /inheritance:r /grant "Administrators:F" "SYSTEM:F" | Out-Null
    Write-Host "[SAFI_WIN] Installed in $adminFile with strict ACLs"
} else {
    $userDir = "$env:USERPROFILE\.ssh"
    if (!(Test-Path $userDir)) { New-Item -ItemType Directory -Force -Path $userDir | Out-Null }
    $userFile = "$userDir\authorized_keys"
    
    $existing = if (Test-Path $userFile) { Get-Content -Raw $userFile } else { "" }
    if ($existing -notmatch [regex]::Escape($key.Trim())) {
        Add-Content -Force -Path $userFile -Value $key.Trim()
    }
    
    & icacls.exe $userFile /inheritance:r /grant "$($env:USERNAME):F" "SYSTEM:F" | Out-Null
    Write-Host "[SAFI_WIN] Installed in $userFile with strict ACLs"
}
PSEOF
)
    PS_DEPLOY="${PS_DEPLOY/__KEY_PLACEHOLDER__/$KEY_CONTENT}"
    B64_PS=$(echo -n "$PS_DEPLOY" | iconv -f UTF-8 -t UTF-16LE | base64 -w 0)

    ssh -o StrictHostKeyChecking=accept-new -p "$PORT" "${USER}@${HOST}" "powershell.exe -NoProfile -NonInteractive -EncodedCommand $B64_PS"

else
    echo ""
    echo "Installing key to Linux host via ssh-copy-id..."
    echo "You will be prompted for ${USER}@${HOST}'s password once."
    echo ""

    if command -v ssh-copy-id &>/dev/null; then
        ssh-copy-id -o StrictHostKeyChecking=accept-new -i "$PUB_KEY" -p "$PORT" "${USER}@${HOST}"
    else
        # Fallback manual install if ssh-copy-id is unavailable
        ssh -o StrictHostKeyChecking=accept-new -p "$PORT" "${USER}@${HOST}" \
            "mkdir -p ~/.ssh && chmod 700 ~/.ssh && (grep -qF '$KEY_CONTENT' ~/.ssh/authorized_keys 2>/dev/null || echo '$KEY_CONTENT' >> ~/.ssh/authorized_keys) && chmod 600 ~/.ssh/authorized_keys"
    fi
fi

# 5. Final Verification
echo ""
echo -n "Verifying passwordless SSH connection... "
if ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 -p "$PORT" "${USER}@${HOST}" "echo OK" &>/dev/null; then
    echo "SUCCESS! ✓"
    echo "=========================================================="
    echo "✓ Key authentication successfully configured for ${USER}@${HOST}"
    echo "=========================================================="
    if [ "$IS_INVENTORY" -eq 1 ]; then
        echo ""
        echo "Target '$TARGET' is now ready for autonomous SAFi sysadmin execution:"
        echo "   sys-exec $TARGET \"uptime\""
        echo ""
    fi
else
    echo "FAILED"
    echo "Warning: Could not connect passwordlessly after installation." >&2
    echo "Please check SSH server logs or permissions on ${HOST}." >&2
    exit 1
fi
