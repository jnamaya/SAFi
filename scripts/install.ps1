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
  "example-server": {
    "host": "192.168.1.100",
    "user": "admin",
    "port": 22,
    "auth": "key",
    "description": "Example target server"
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
        wsl.exe -e sh -c "mkdir -p ~/.config 2>/dev/null; ln -sf '$wslWinConfig' ~/.config/safi 2>/dev/null || true" 2>$null
    }
} catch {
    # Ignore if WSL path conversion fails
}

# 4. Pre-install all Linux operational dependencies using WSL root bridge (no sudo password needed)
Write-Host "Ensuring core operational utilities (ssh, sshpass, nmap, jq, curl, rsync, python3) in WSL..." -ForegroundColor Cyan
wsl.exe -u root -e sh -c "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-pip python3-venv ssh sshpass nmap jq curl iputils-ping dnsutils rsync git" 2>$null

# 5. Run the SAFi CLI installer inside WSL
Write-Host "Installing SAFi CLI in WSL..." -ForegroundColor Cyan
wsl.exe -e bash -c "(curl -sSL https://runsafi.com/install.sh 2>/dev/null || curl -sSL https://raw.githubusercontent.com/jnamaya/SAFi/dev/scripts/install_cli.sh) | bash"

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
