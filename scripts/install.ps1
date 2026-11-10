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
    @'
{
  "example-server": {
    "host": "192.168.1.100",
    "user": "admin",
    "port": 22,
    "auth": "key",
    "description": "Example target server"
  }
}
'@ | Set-Content -Path $winInvFile -Encoding UTF8
    Write-Host "Scaffolded inventory in $winInvFile" -ForegroundColor Cyan
}

# 4. Pre-install all Linux operational dependencies using WSL root bridge (no sudo password needed)
Write-Host "Ensuring core operational utilities (ssh, sshpass, nmap, jq, curl, rsync, python3) in WSL..." -ForegroundColor Cyan
wsl.exe -u root -e sh -c "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-pip python3-venv ssh sshpass nmap jq curl iputils-ping dnsutils rsync git" 2>$null

# 5. Run the SAFi CLI installer inside WSL
Write-Host "Installing SAFi CLI and configuring Windows bridges..." -ForegroundColor Cyan
wsl.exe -e bash -c "(curl -sSL https://runsafi.com/install.sh 2>/dev/null || curl -sSL https://raw.githubusercontent.com/jnamaya/SAFi/dev/scripts/install_cli.sh) | bash"

Write-Host ""
Write-Host "=== SAFi CLI Installation Complete ===" -ForegroundColor Green
Write-Host "Available commands in PowerShell & CMD:" -ForegroundColor Cyan
Write-Host "  safi-cli             Launch interactive SAFi agent session"
Write-Host "  saficli --setup      Run connection and model setup wizard"
Write-Host "  sys-exec <host> <cmd> Execute commands on managed infrastructure"
Write-Host "  safi-setup-key <tgt> Deploy SSH key for passwordless agent access"
Write-Host ""
