# SAFi Windows PowerShell Installer
# Installs and bridges safi-cli, saficli, sys-exec, and safi-setup-key into Windows

$ErrorActionPreference = "Stop"

Write-Host "=== SAFi Governed Agent Interface - Windows CLI Installer ===" -ForegroundColor Cyan

# 1. Verify WSL availability
$wslCmd = Get-Command "wsl.exe" -ErrorAction SilentlyContinue
if (-not $wslCmd) {
    Write-Error "Windows Subsystem for Linux (WSL) is not enabled on this system. Run 'wsl --install' in an elevated PowerShell to enable WSL."
    exit 1
}

# 2. Check if a default WSL distro is installed
$wslDistros = wsl.exe --list --quiet 2>$null
if (-not $wslDistros -or $wslDistros.Count -eq 0) {
    Write-Host "No WSL distribution found. Installing Ubuntu..." -ForegroundColor Yellow
    wsl.exe --install -d Ubuntu --no-launch
    Write-Host "Ubuntu installed. Please restart if prompted by Windows." -ForegroundColor Green
}

# 3. Scaffold Windows user profile configuration directory (~/.config/safi)
$winConfigDir = Join-Path $env:USERPROFILE ".config\safi"
if (-not (Test-Path $winConfigDir)) {
    New-Item -ItemType Directory -Force -Path $winConfigDir | Out-Null
}
$winInvFile = Join-Path $winConfigDir "inventory.json"
if (-not (Test-Path $winInvFile)) {
    $invTemplate = @'
{
  "example-linux-server": {
    "host": "192.168.1.100",
    "user": "admin",
    "port": 22,
    "auth": "key",
    "key_path": "~/.ssh/id_ed25519",
    "os": "linux",
    "description": "Example Linux target server (replace with your host details)"
  },
  "example-windows-server": {
    "host": "192.168.1.101",
    "user": "administrator",
    "port": 22,
    "auth": "key",
    "key_path": "~/.ssh/id_ed25519",
    "os": "windows",
    "description": "Example Windows target server over OpenSSH"
  }
}
'@
    [System.IO.File]::WriteAllText($winInvFile, $invTemplate, (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "Scaffolded inventory in $winInvFile" -ForegroundColor Cyan
} else {
    # Ensure existing file has no UTF-8 BOM which breaks json parsers
    try {
        $rawBytes = [System.IO.File]::ReadAllBytes($winInvFile)
        if ($rawBytes.Length -ge 3 -and $rawBytes[0] -eq 0xEF -and $rawBytes[1] -eq 0xBB -and $rawBytes[2] -eq 0xBF) {
            $cleaned = [System.Text.Encoding]::UTF8.GetString($rawBytes, 3, $rawBytes.Length - 3)
            [System.IO.File]::WriteAllText($winInvFile, $cleaned, (New-Object System.Text.UTF8Encoding($false)))
        }
    } catch { }
}

# 3b. Link Windows .config\safi into WSL user ~/.config/safi
try {
    $wslWinConfig = (wsl.exe -e wslpath -u "$winConfigDir" 2>$null).Trim()
    if ($wslWinConfig) {
        wsl.exe -e bash -c "mkdir -p ~/.config 2>/dev/null; if [ -d ~/.config/safi ] && [ ! -L ~/.config/safi ]; then rm -rf ~/.config/safi 2>/dev/null || true; fi; ln -sfn '$wslWinConfig' ~/.config/safi 2>/dev/null || true" 2>$null
        Write-Host "Linked Windows config directory directly to WSL ~/.config/safi" -ForegroundColor Green
    }
} catch {
    # Ignore if WSL path conversion fails
}

# 4. Pre-install all Linux operational dependencies using WSL root bridge (no sudo password needed)
# Note: Ubuntu WSL ships an apt hook (20snapd.conf / advise-snap) that aborts apt-get when snapd
# is absent. Pipe the script via stdin to avoid PowerShell CreateProcess quote mangling, and
# temporarily stash any advise-snap hook during apt-get (restored automatically on exit).
Write-Host "Ensuring core operational utilities (ssh, sshpass, nmap, jq, curl, rsync, python3, git) in WSL..." -ForegroundColor Cyan
$aptScript = @'
set -u
STASH_DIR=$(mktemp -d /tmp/safi-apt-stash.XXXXXX)
restore_hooks() {
    for d in etc usr; do
        if [ -d "$STASH_DIR/$d" ]; then
            dest="/etc/apt/apt.conf.d"
            [ "$d" = "usr" ] && dest="/usr/share/apt/apt.conf.d"
            for f in "$STASH_DIR/$d"/*; do
                [ -e "$f" ] && mv "$f" "$dest/$(basename "$f")" 2>/dev/null || true
            done
        fi
    done
    rm -rf "$STASH_DIR" 2>/dev/null || true
}
trap restore_hooks EXIT

for pair in "etc:/etc/apt/apt.conf.d" "usr:/usr/share/apt/apt.conf.d"; do
    key="${pair%%:*}"
    dir="${pair#*:}"
    if [ -d "$dir" ]; then
        mkdir -p "$STASH_DIR/$key"
        for f in "$dir"/*; do
            [ -f "$f" ] || continue
            if grep -q "advise-snap" "$f" 2>/dev/null; then
                mv "$f" "$STASH_DIR/$key/" 2>/dev/null || true
            fi
        done
    fi
done

apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-pip python3-venv openssh-client sshpass nmap jq curl iputils-ping dnsutils rsync git
'@
$aptScriptLf = ($aptScript -replace "`r`n", "`n")
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$aptScriptLf | wsl.exe -u root -e sh -s
$aptExit = $LASTEXITCODE
$ErrorActionPreference = $prevEap
if ($aptExit -ne 0) {
    Write-Host "Warning: WSL package pre-install returned exit code $aptExit; continuing with CLI install..." -ForegroundColor Yellow
}

# 5. Fetch the Linux installer on Windows (does not require curl inside WSL) and run it inside WSL
Write-Host "Installing SAFi CLI in WSL..." -ForegroundColor Cyan
$installSh = $null
try {
    $installSh = Invoke-RestMethod -Uri "https://runsafi.com/install.sh" -UseBasicParsing
} catch {
    $installSh = Invoke-RestMethod -Uri "https://raw.githubusercontent.com/jnamaya/SAFi/main/scripts/install_cli.sh" -UseBasicParsing
}
$installShLf = ($installSh -replace "`r`n", "`n")
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$installShLf | wsl.exe -e bash -s
$wslInstallExit = $LASTEXITCODE
$ErrorActionPreference = $prevEap
if ($wslInstallExit -ne 0) {
    Write-Error "SAFi CLI installation inside WSL failed (exit code $wslInstallExit)."
    exit $wslInstallExit
}

# Verify saficli binary is actually present in WSL before claiming success
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
wsl.exe -e bash -lic "command -v saficli >/dev/null 2>&1"
$verifyExit = $LASTEXITCODE
$ErrorActionPreference = $prevEap
if ($verifyExit -ne 0) {
    Write-Error "SAFi CLI binary 'saficli' was not found in WSL PATH after install. Please check the output above."
    exit 1
}

# 6. Configure Windows Bridges (PowerShell & CMD wrappers)
Write-Host "Configuring Windows bridges in user profile and PATH..." -ForegroundColor Cyan
$localBin = Join-Path $env:USERPROFILE ".local\bin"
if (-not (Test-Path $localBin)) {
    New-Item -ItemType Directory -Force -Path $localBin | Out-Null
}

$tools = @("safi-cli", "saficli", "sys-exec", "safi-setup-key")
foreach ($t in $tools) {
    $cmdContent = "@echo off`r`nwsl.exe -e bash -lic `"exec $t \""`$@\""`" bash %*`r`nexit /b %ERRORLEVEL%`r`n"
    $cmdPath = Join-Path $localBin "$t.cmd"
    [System.IO.File]::WriteAllText($cmdPath, $cmdContent, [System.Text.Encoding]::ASCII)
}

# Also bridge into WindowsApps if available (default system PATH location)
$winAppsDir = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"
if (Test-Path $winAppsDir) {
    foreach ($t in $tools) {
        $cmdContent = "@echo off`r`nwsl.exe -e bash -lic `"exec $t \""`$@\""`" bash %*`r`nexit /b %ERRORLEVEL%`r`n"
        $cmdPath = Join-Path $winAppsDir "$t.cmd"
        try {
            [System.IO.File]::WriteAllText($cmdPath, $cmdContent, [System.Text.Encoding]::ASCII)
        } catch {
            # Ignore if permission restricted
        }
    }
}

# Persist to User Path in registry
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($userPath -notlike "*$localBin*") {
    [Environment]::SetEnvironmentVariable('Path', "$userPath;$localBin".Trim(';'), 'User')
}

# Update current session PATH immediately so commands work right away
if ($env:Path -notlike "*$localBin*") {
    $env:Path = "$localBin;$env:Path"
}

Write-Host ""
Write-Host "=== SAFi CLI Installation Complete ===" -ForegroundColor Green
Write-Host "Available commands in PowerShell & CMD:" -ForegroundColor Cyan
Write-Host "  safi-cli             Launch interactive SAFi agent session"
Write-Host "  saficli --setup      Run connection and model setup wizard"
Write-Host "  sys-exec <host> <cmd> Execute commands on managed infrastructure"
Write-Host "  safi-setup-key <tgt> Deploy SSH key for passwordless agent access"
Write-Host ""
