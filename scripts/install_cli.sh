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
    if [ -f "${REPO_DIR}/scripts/setup_ssh_key.sh" ]; then
        cp "${REPO_DIR}/scripts/setup_ssh_key.sh" "${INSTALL_DIR}/setup_ssh_key.sh"
        chmod +x "${INSTALL_DIR}/setup_ssh_key.sh"
    fi
else
    SAFI_BRANCH="${SAFI_BRANCH:-dev}"
    echo "Downloading safi_cli package from repository (${SAFI_BRANCH} branch)..."
    rm -rf "${INSTALL_DIR}/safi_cli"
    TMP_DIR=$(mktemp -d)
    git clone --depth 1 --branch "${SAFI_BRANCH}" https://github.com/jnamaya/SAFi.git "${TMP_DIR}/safi-repo"
    cp -r "${TMP_DIR}/safi-repo/safi_cli" "${INSTALL_DIR}/"
    if [ -f "${TMP_DIR}/safi-repo/scripts/setup_ssh_key.sh" ]; then
        cp "${TMP_DIR}/safi-repo/scripts/setup_ssh_key.sh" "${INSTALL_DIR}/setup_ssh_key.sh"
        chmod +x "${INSTALL_DIR}/setup_ssh_key.sh"
    fi
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

if ! "${PYTHON_BIN}" -c 'import ensurepip' &>/dev/null; then
    PKGS+=("python3-venv" "python3-pip")
fi

if [ ${#PKGS[@]} -gt 0 ]; then
    echo "Installing missing system utilities: ${PKGS[*]}..."
    if command -v apt-get &>/dev/null && [ "$(id -u)" -eq 0 ]; then
        apt-get update -qq && apt-get install -y -qq "${PKGS[@]}" || true
    elif command -v apt-get &>/dev/null && command -v sudo &>/dev/null; then
        sudo -n apt-get update -qq && sudo -n apt-get install -y -qq "${PKGS[@]}" 2>/dev/null || true
    fi
fi

# 4. Setup Python runtime (isolated venv preferred)
TARGET_PYTHON="${PYTHON_BIN}"
USE_VENV=0

if "${PYTHON_BIN}" -m venv "${INSTALL_DIR}/venv" 2>/dev/null; then
    if [ -f "${INSTALL_DIR}/venv/bin/pip" ]; then
        echo "Created isolated venv in ${INSTALL_DIR}/venv"
        "${INSTALL_DIR}/venv/bin/pip" install --quiet requests rich prompt_toolkit
        TARGET_PYTHON="${INSTALL_DIR}/venv/bin/python"
        USE_VENV=1
    fi
fi

if [ "${USE_VENV}" -eq 0 ]; then
    if "${PYTHON_BIN}" -c "import requests, rich, prompt_toolkit" 2>/dev/null; then
        echo "Using existing Python environment (requests, rich, and prompt_toolkit already present)."
        TARGET_PYTHON="${PYTHON_BIN}"
    else
        echo "Attempting to install 'requests', 'rich', and 'prompt_toolkit'..."
        if "${PYTHON_BIN}" -m pip install --user requests rich prompt_toolkit 2>/dev/null || "${PYTHON_BIN}" -m pip install --user --break-system-packages requests rich prompt_toolkit 2>/dev/null; then
            TARGET_PYTHON="${PYTHON_BIN}"
        else
            echo "Warning: could not auto-install requests and rich."
            echo "Hint: Install python3-venv with 'sudo apt update && sudo apt install -y python3-venv python3-pip' and re-run."
        fi
    fi
fi

# 5. Create launcher script
echo "Writing launcher to ${BIN_DIR}/safi-cli..."
cat << EOF > "${BIN_DIR}/safi-cli"
#!/usr/bin/env bash
if [ -d "${REPO_DIR}/safi_cli" ]; then
    export PYTHONPATH="${REPO_DIR}:\${PYTHONPATH}"
elif [ -d "/var/www/safi/safi_cli" ]; then
    export PYTHONPATH="/var/www/safi:\${PYTHONPATH}"
else
    export PYTHONPATH="${INSTALL_DIR}:\${PYTHONPATH}"
fi
exec "${TARGET_PYTHON}" -m safi_cli.main "\$@"
EOF
chmod +x "${BIN_DIR}/safi-cli"
ln -sf "${BIN_DIR}/safi-cli" "${BIN_DIR}/saficli"

# Remove legacy 'safi' CLI wrapper from user bin if it shadows appliance tools
if [ -f "${BIN_DIR}/safi" ] && grep -q "safi_cli.main" "${BIN_DIR}/safi" 2>/dev/null; then
    rm -f "${BIN_DIR}/safi"
fi

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
    mkdir -p "$(dirname "$INVENTORY_FILE")"
    echo "{}" > "$INVENTORY_FILE"
fi

if [ "$1" = "--list" ] || [ "$1" = "-l" ]; then
    echo "Managed Infrastructure Inventory ($INVENTORY_FILE):"
    python3 - "$INVENTORY_FILE" << 'PYEOF' 2>/dev/null || true
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
    for k, v in data.items():
        user = v.get("user") or "(ssh-config)"
        host = v.get("host") or ""
        auth = v.get("auth") or "key"
        desc = v.get("description") or ""
        print(f"  - {k}: {user}@{host} (auth: {auth}) - {desc}")
except Exception:
    pass
PYEOF
    exit 0
fi

if [ $# -lt 2 ]; then
    echo "Error: Missing command to execute." >&2
    usage
fi

TARGET="$1"
shift
CMD="$*"

eval "$(python3 - "$INVENTORY_FILE" "$TARGET" << 'PYEOF' 2>/dev/null || echo "FOUND=0"
import json, sys, shlex

inv_file, target = sys.argv[1], sys.argv[2]
data = {}
try:
    with open(inv_file) as f:
        data = json.load(f)
except Exception:
    pass

cfg = data.get(target)
if not cfg:
    for k, v in data.items():
        if k.lower() == target.lower():
            cfg = v
            break

if cfg:
    host = str(cfg.get("host") or "")
    if host.startswith("ssh "):
        host = host[4:]
    user = str(cfg.get("user") or "").strip()
    port = str(cfg.get("port") or "").strip()
    auth = str(cfg.get("auth") or "key").strip()
    desc = str(cfg.get("description") or "").strip()
    os_type = str(cfg.get("os") or "").strip()
    print(f"FOUND=1; HOST={shlex.quote(host)}; USER={shlex.quote(user)}; PORT={shlex.quote(port)}; AUTH={shlex.quote(auth)}; DESC={shlex.quote(desc)}; OS_TYPE={shlex.quote(os_type)}")
else:
    print("FOUND=0")
PYEOF
)"

if [ "$FOUND" = "1" ]; then
    : # Target resolved from inventory
elif [[ "$TARGET" == *"@"* ]] || [[ "$TARGET" =~ ^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]] || [[ "$TARGET" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    if [[ "$TARGET" == *"@"* ]]; then
        USER="${TARGET%%@*}"
        HOST="${TARGET#*@}"
    else
        USER="root"
        HOST="$TARGET"
    fi
    PORT=22
    AUTH="key"
    DESC=""
    OS_TYPE="linux"
else
    echo "Error: Unknown host alias '$TARGET'. Available hosts:" >&2
    python3 - "$INVENTORY_FILE" << 'PYEOF' 2>/dev/null || true >&2
import json, sys
try:
    with open(sys.argv[1]) as f:
        for k in json.load(f).keys():
            print(f"  - {k}")
except Exception:
    pass
PYEOF
    exit 1
fi

# Automatically wrap PowerShell commands on Windows targets into UTF-16LE Base64 (-EncodedCommand)
# with -NoProfile -NonInteractive -InputFormat None. Fast commands use $ProgressPreference='SilentlyContinue',
# while long-running Install-*/Uninstall-* commands stream live progress via CLIXML parsed below.
if [[ "${OS_TYPE,,}" == *"win"* ]] || [[ "${DESC,,}" == *"windows"* ]] || [[ "${TARGET,,}" == *"win"* ]] || [[ "$CMD" =~ ^[[:space:]]*(powershell|pwsh)(\.exe)?[[:space:]] ]]; then
    if command -v python3 &>/dev/null; then
        CMD=$(python3 - "$TARGET" "$CMD" << 'PYEOF'
import base64, re, sys

target = sys.argv[1].strip()
raw = sys.argv[2].strip()
m = re.match(
    r'^(?:powershell|pwsh)(?:\.exe)?(?:\s+-(?:NoProfile|NonInteractive|NoLogo|InputFormat\s+\S+|ExecutionPolicy\s+\S+))*\s+(?:-(?:Command|c))\s+(.*)\Z',
    raw,
    re.IGNORECASE | re.DOTALL,
)
inner = m.group(1).strip() if m else raw
if len(inner) >= 2 and inner[0] == inner[-1] and inner[0] in ('"', "'"):
    quote_char = inner[0]
    inner = inner[1:-1]
    if quote_char == '"':
        inner = re.sub(r'\\+"', '"', inner).replace(r'\\', '\\')

is_long_op = bool(
    re.search(
        r'\b(?:Install|Uninstall|Update|Restore|Backup)-(?:WindowsFeature|ADDS\w+|Package|Module)\b',
        inner,
        re.IGNORECASE,
    )
    and not re.search(r'\bStart-Job\b', inner, re.IGNORECASE)
)

if is_long_op:
    script = f"""$ProgressPreference = 'SilentlyContinue'
$__safi_t0 = [DateTime]::UtcNow
$__safi_job = Start-Job -ScriptBlock {{
{inner}
}}
$__safi_last = ""
$__safi_last_ts = [DateTime]::UtcNow
while ($__safi_job.State -eq 'Running') {{
    $__now = [DateTime]::UtcNow
    $__elapsed = [int]($__now - $__safi_t0).TotalSeconds
    $__p = $__safi_job.ChildJobs[0].Progress | Where-Object {{ $_.Activity -and ($_.Activity -notmatch 'Preparing modules') }} | Select-Object -Last 1
    $__procs = @(Get-Process TiWorker,dsamain,ServerManager -ErrorAction SilentlyContinue | Select-Object -ExpandProperty ProcessName -Unique)
    $__proc_note = if ($__procs.Count -gt 0) {{ " [" + ($__procs -join ",") + " active]" }} else {{ "" }}
    if ($__p) {{
        $__pct = if ($__p.PercentComplete -ge 0) {{ "$($__p.PercentComplete)% " }} else {{ "" }}
        $__sd = if ($__p.StatusDescription -and ($__p.StatusDescription.Trim() -ne "$($__p.PercentComplete)%")) {{ ": $($__p.StatusDescription)" }} else {{ "" }}
        $__base = "[{target}] ${{__pct}}$($__p.Activity)${{__sd}}${{__proc_note}}"
        if ($__base -ne $__safi_last -or ($__now - $__safi_last_ts).TotalSeconds -ge 10) {{
            [Console]::Out.WriteLine("[SAFI_PROGRESS] $__base (${{__elapsed}}s)")
            [Console]::Out.Flush()
            $__safi_last = $__base
            $__safi_last_ts = $__now
        }}
    }} elseif (($__now - $__safi_last_ts).TotalSeconds -ge 10) {{
        [Console]::Out.WriteLine("[SAFI_PROGRESS] [{target}] Running operation${{__proc_note}} (${{__elapsed}}s)")
        [Console]::Out.Flush()
        $__safi_last_ts = $__now
    }}
    Start-Sleep -Seconds 2
}}
$__safi_job.ChildJobs[0].Progress.Clear()
Receive-Job -Job $__safi_job -Wait | Out-String -Width 240
if ($__safi_job.ChildJobs[0].Error.Count -gt 0) {{
    foreach ($__err in $__safi_job.ChildJobs[0].Error) {{
        [Console]::Error.WriteLine($__err.ToString())
    }}
}}
"""
else:
    script = "$ProgressPreference = 'SilentlyContinue'; " + inner
encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
print(f"powershell.exe -NoProfile -NonInteractive -InputFormat None -EncodedCommand {encoded}")
PYEOF
)
    fi
fi

SSH_OPTS=(-n -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=3)
if [ -n "$PORT" ] && [ "$PORT" != "null" ]; then
    SSH_OPTS+=(-p "$PORT")
fi

if [ -n "$USER" ] && [ "$USER" != "null" ]; then
    DEST="${USER}@${HOST}"
else
    DEST="${HOST}"
fi

if [ "$AUTH" = "key" ] || [ "$AUTH" = "ssh" ] || [ "$AUTH" = "ssh_config" ]; then
    if command -v python3 &>/dev/null; then
        python3 - "$TARGET" "$DEST" "$CMD" "${SSH_OPTS[@]}" << 'PYEOF'
import html, re, subprocess, sys, threading, time

target = sys.argv[1]
dest = sys.argv[2]
cmd = sys.argv[3]
ssh_opts = sys.argv[4:]

ssh_cmd = ["ssh", "-o", "BatchMode=yes", *ssh_opts, dest, cmd]
proc = subprocess.Popen(
    ssh_cmd,
    stdin=subprocess.DEVNULL,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    bufsize=1,
)

start_ts = time.time()
last_activity_ts = start_ts
lock = threading.Lock()

def _read_out():
    global last_activity_ts
    if not proc.stdout:
        return
    for line in iter(proc.stdout.readline, ""):
        with lock:
            last_activity_ts = time.time()
            sys.stdout.write(line)
            sys.stdout.flush()

def _read_err():
    global last_activity_ts
    if not proc.stderr:
        return
    import os
    fd = proc.stderr.fileno()
    last_prog = ""
    clixml_mode = False
    buf = ""
    while True:
        try:
            chunk_bytes = os.read(fd, 4096)
        except Exception:
            break
        if not chunk_bytes:
            break
        text = chunk_bytes.decode("utf-8", errors="replace")
        if "#< CLIXML" in text or "<Objs " in text or clixml_mode:
            clixml_mode = True
            buf += text
            while True:
                m_err = re.search(r'<S S="Error">(.*?)</S>', buf, re.DOTALL)
                if not m_err:
                    break
                err_raw = m_err.group(1)
                buf = buf[m_err.end():]
                err_txt = html.unescape(err_raw).replace("_x000D__x000A_", "\n").replace("_x000A_", "\n")
                if err_txt.strip():
                    with lock:
                        last_activity_ts = time.time()
                        sys.stderr.write(err_txt)
                        if not err_txt.endswith("\n"):
                            sys.stderr.write("\n")
                        sys.stderr.flush()
            if len(buf) > 65536:
                buf = buf[-16384:]
        else:
            with lock:
                last_activity_ts = time.time()
                sys.stderr.write(text)
                sys.stderr.flush()

t_out = threading.Thread(target=_read_out, daemon=True)
t_err = threading.Thread(target=_read_err, daemon=True)
t_out.start()
t_err.start()

while proc.poll() is None:
    time.sleep(1.0)
    now = time.time()
    with lock:
        idle = now - last_activity_ts
        if idle >= 15.0:
            elapsed = int(now - start_ts)
            sys.stdout.write(f"[SAFI_PROGRESS] [{target}] running ({elapsed}s)\n")
            sys.stdout.flush()
            last_activity_ts = now

t_out.join(timeout=1.0)
t_err.join(timeout=1.0)
sys.exit(proc.returncode or 0)
PYEOF
        exit $?
    else
        ssh -o BatchMode=yes "${SSH_OPTS[@]}" "$DEST" "$CMD"
        exit $?
    fi
elif [ "$AUTH" = "password" ]; then
    echo "Error: Plain-text password storage has been disabled for security. Please configure SSH key-based authentication for '$TARGET' (e.g. ssh-copy-id)." >&2
    exit 1
else
    echo "Error: Unsupported auth method '$AUTH' for '$TARGET'. Please use SSH key-based authentication." >&2
    exit 1
fi
EOF
chmod +x "${BIN_DIR}/sys-exec"

# 6b. Install safi-setup-key runner
echo "Writing safi-setup-key runner to ${BIN_DIR}/safi-setup-key..."
if [ -f "${INSTALL_DIR}/setup_ssh_key.sh" ]; then
    cp "${INSTALL_DIR}/setup_ssh_key.sh" "${BIN_DIR}/safi-setup-key"
    chmod +x "${BIN_DIR}/safi-setup-key"
elif [ -f "${REPO_DIR}/scripts/setup_ssh_key.sh" ]; then
    cp "${REPO_DIR}/scripts/setup_ssh_key.sh" "${INSTALL_DIR}/setup_ssh_key.sh"
    cp "${REPO_DIR}/scripts/setup_ssh_key.sh" "${BIN_DIR}/safi-setup-key"
    chmod +x "${INSTALL_DIR}/setup_ssh_key.sh" "${BIN_DIR}/safi-setup-key"
else
    cat << EOF > "${BIN_DIR}/safi-setup-key"
#!/usr/bin/env bash
if [ -d "${REPO_DIR}/safi_cli" ]; then
    export PYTHONPATH="${REPO_DIR}:\${PYTHONPATH}"
elif [ -d "/var/www/safi/safi_cli" ]; then
    export PYTHONPATH="/var/www/safi:\${PYTHONPATH}"
else
    export PYTHONPATH="${INSTALL_DIR}:\${PYTHONPATH}"
fi
exec "${TARGET_PYTHON}" -m safi_cli.ssh_keys "\$@"
EOF
    chmod +x "${BIN_DIR}/safi-setup-key"
fi

# 7. Make safi-cli, saficli, sys-exec, and safi-setup-key universally available in system PATH
if [ -w "/usr/local/bin" ]; then
    ln -sf "${BIN_DIR}/safi-cli" /usr/local/bin/safi-cli 2>/dev/null || true
    ln -sf "${BIN_DIR}/safi-cli" /usr/local/bin/saficli 2>/dev/null || true
    ln -sf "${BIN_DIR}/sys-exec" /usr/local/bin/sys-exec 2>/dev/null || true
    ln -sf "${BIN_DIR}/safi-setup-key" /usr/local/bin/safi-setup-key 2>/dev/null || true
    # Restore appliance tool if legacy symlink existed
    if [ -L "/usr/local/bin/safi" ] && [ "$(readlink /usr/local/bin/safi 2>/dev/null)" = "${BIN_DIR}/safi" ]; then
        rm -f /usr/local/bin/safi
        [ -x "/usr/local/sbin/safi" ] && ln -sf /usr/local/sbin/safi /usr/local/bin/safi 2>/dev/null || true
    fi
elif command -v sudo &>/dev/null; then
    sudo -n ln -sf "${BIN_DIR}/safi-cli" /usr/local/bin/safi-cli 2>/dev/null || true
    sudo -n ln -sf "${BIN_DIR}/safi-cli" /usr/local/bin/saficli 2>/dev/null || true
    sudo -n ln -sf "${BIN_DIR}/sys-exec" /usr/local/bin/sys-exec 2>/dev/null || true
    sudo -n ln -sf "${BIN_DIR}/safi-setup-key" /usr/local/bin/safi-setup-key 2>/dev/null || true
    # Restore appliance tool if legacy symlink existed
    if [ -L "/usr/local/bin/safi" ] && [ "$(readlink /usr/local/bin/safi 2>/dev/null)" = "${BIN_DIR}/safi" ]; then
        sudo -n rm -f /usr/local/bin/safi 2>/dev/null || true
        [ -x "/usr/local/sbin/safi" ] && sudo -n ln -sf /usr/local/sbin/safi /usr/local/bin/safi 2>/dev/null || true
    fi
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
# If running inside WSL, bridge safi-cli to Windows
if grep -qi "microsoft" /proc/version 2>/dev/null && command -v cmd.exe &>/dev/null; then
    echo "Detected WSL environment - configuring Windows PowerShell & CMD integration..."
    WIN_APPS_RAW=$(cmd.exe /c "echo %LOCALAPPDATA%\Microsoft\WindowsApps" 2>/dev/null | tr -d '\r')
    if [ -n "$WIN_APPS_RAW" ] && command -v wslpath &>/dev/null; then
        WIN_APPS_DIR=$(wslpath "$WIN_APPS_RAW" 2>/dev/null || true)
        if [ -n "$WIN_APPS_DIR" ] && [ -d "$WIN_APPS_DIR" ]; then
            cat << 'EOF' > "${WIN_APPS_DIR}/safi-cli.cmd"
@echo off
wsl.exe -e bash -lic "exec safi-cli \"$@\"" bash %*
exit /b %ERRORLEVEL%
EOF
            cat << 'EOF' > "${WIN_APPS_DIR}/saficli.cmd"
@echo off
wsl.exe -e bash -lic "exec saficli \"$@\"" bash %*
exit /b %ERRORLEVEL%
EOF
            cat << 'EOF' > "${WIN_APPS_DIR}/sys-exec.cmd"
@echo off
wsl.exe -e bash -lic "exec sys-exec \"$@\"" bash %*
exit /b %ERRORLEVEL%
EOF
            cat << 'EOF' > "${WIN_APPS_DIR}/safi-setup-key.cmd"
@echo off
wsl.exe -e bash -lic "exec safi-setup-key \"$@\"" bash %*
exit /b %ERRORLEVEL%
EOF
            chmod +x "${WIN_APPS_DIR}/safi-cli.cmd" "${WIN_APPS_DIR}/saficli.cmd" "${WIN_APPS_DIR}/sys-exec.cmd" "${WIN_APPS_DIR}/safi-setup-key.cmd" 2>/dev/null || true
            echo "✓ Created Windows bridge in ${WIN_APPS_RAW} (safi-cli.cmd, saficli.cmd, sys-exec.cmd, safi-setup-key.cmd)"
        fi
    fi

    WIN_PROFILE_RAW=$(cmd.exe /c "echo %USERPROFILE%" 2>/dev/null | tr -d '\r')
    if [ -n "$WIN_PROFILE_RAW" ] && command -v wslpath &>/dev/null; then
        WIN_PROFILE_DIR=$(wslpath "$WIN_PROFILE_RAW" 2>/dev/null || true)
        if [ -n "$WIN_PROFILE_DIR" ] && [ -d "$WIN_PROFILE_DIR" ]; then
            mkdir -p "${WIN_PROFILE_DIR}/.local/bin"
            cat << 'EOF' > "${WIN_PROFILE_DIR}/.local/bin/safi-cli.cmd"
@echo off
wsl.exe -e bash -lic "exec safi-cli \"$@\"" bash %*
exit /b %ERRORLEVEL%
EOF
            cat << 'EOF' > "${WIN_PROFILE_DIR}/.local/bin/saficli.cmd"
@echo off
wsl.exe -e bash -lic "exec saficli \"$@\"" bash %*
exit /b %ERRORLEVEL%
EOF
            cat << 'EOF' > "${WIN_PROFILE_DIR}/.local/bin/sys-exec.cmd"
@echo off
wsl.exe -e bash -lic "exec sys-exec \"$@\"" bash %*
exit /b %ERRORLEVEL%
EOF
            cat << 'EOF' > "${WIN_PROFILE_DIR}/.local/bin/safi-setup-key.cmd"
@echo off
wsl.exe -e bash -lic "exec safi-setup-key \"$@\"" bash %*
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

# Auto-configure default appliance URL if running on a SAFi appliance
if [ -f "/etc/systemd/system/safi.service" ] || [ -d "/var/lib/safi-firstboot" ]; then
    if [ ! -f "${CONFIG_DIR}/config.json" ] || ! grep -q '"api_url"' "${CONFIG_DIR}/config.json" 2>/dev/null; then
        echo '{"api_url": "https://localhost"}' > "${CONFIG_DIR}/config.json"
        chmod 0600 "${CONFIG_DIR}/config.json"
        echo "Detected local appliance environment — configured default URL: https://localhost"
    fi
fi

echo ""
echo "=========================================================="
echo "✓ SAFi CLI installed successfully!"
echo "=========================================================="
echo ""
echo "To get started, simply run:"
echo "   safi-cli"
echo "   (or: saficli)"
echo ""
