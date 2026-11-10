# SAFi Windows PowerShell Uninstaller
# Completely removes all Windows wrappers, user profile directories (.config, .local, .safi),
# and the WSL Linux installation.

$ErrorActionPreference = "SilentlyContinue"

Write-Host "=== SAFi CLI Windows Uninstaller ===" -ForegroundColor Cyan

# 1. Remove Windows command wrappers from WindowsApps
$winApps = @(
    "$env:LOCALAPPDATA\Microsoft\WindowsApps\safi-cli.cmd",
    "$env:LOCALAPPDATA\Microsoft\WindowsApps\saficli.cmd",
    "$env:LOCALAPPDATA\Microsoft\WindowsApps\sys-exec.cmd",
    "$env:LOCALAPPDATA\Microsoft\WindowsApps\safi-setup-key.cmd"
)

foreach ($file in $winApps) {
    if (Test-Path $file) {
        Remove-Item -Force $file -ErrorAction SilentlyContinue
        Write-Host "Removed $file" -ForegroundColor Gray
    }
}

# 2. Remove Windows user profile directories (.safi, .config\safi, .local\bin wrappers)
$winSafiDir = Join-Path $env:USERPROFILE ".safi"
if (Test-Path $winSafiDir) {
    Remove-Item -Recurse -Force $winSafiDir -ErrorAction SilentlyContinue
    Write-Host "Removed $winSafiDir" -ForegroundColor Gray
}

$winConfigSafiDir = Join-Path $env:USERPROFILE ".config\safi"
if (Test-Path $winConfigSafiDir) {
    Remove-Item -Recurse -Force $winConfigSafiDir -ErrorAction SilentlyContinue
    Write-Host "Removed $winConfigSafiDir" -ForegroundColor Gray
}

$winConfigDir = Join-Path $env:USERPROFILE ".config"
if (Test-Path $winConfigDir) {
    $remaining = Get-ChildItem -Force $winConfigDir -ErrorAction SilentlyContinue
    if (-not $remaining -or $remaining.Count -eq 0) {
        Remove-Item -Recurse -Force $winConfigDir -ErrorAction SilentlyContinue
        Write-Host "Removed empty $winConfigDir" -ForegroundColor Gray
    }
}

$winLocalBin = Join-Path $env:USERPROFILE ".local\bin"
if (Test-Path $winLocalBin) {
    $targets = @("safi-cli.cmd", "saficli.cmd", "sys-exec.cmd", "safi-setup-key.cmd")
    foreach ($t in $targets) {
        $p = Join-Path $winLocalBin $t
        if (Test-Path $p) {
            Remove-Item -Force $p -ErrorAction SilentlyContinue
            Write-Host "Removed $p" -ForegroundColor Gray
        }
    }
    $remBin = Get-ChildItem -Force $winLocalBin -ErrorAction SilentlyContinue
    if (-not $remBin -or $remBin.Count -eq 0) {
        Remove-Item -Recurse -Force $winLocalBin -ErrorAction SilentlyContinue
    }
}

$winLocal = Join-Path $env:USERPROFILE ".local"
if (Test-Path $winLocal) {
    $remLocal = Get-ChildItem -Force $winLocal -ErrorAction SilentlyContinue
    if (-not $remLocal -or $remLocal.Count -eq 0) {
        Remove-Item -Recurse -Force $winLocal -ErrorAction SilentlyContinue
        Write-Host "Removed empty $winLocal" -ForegroundColor Gray
    }
}

# Clean PATH from User environment if .local\bin was added
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($userPath -and $userPath -like "*\.local\bin*") {
    $cleanedPath = ($userPath.Split(';') | Where-Object { $_ -and $_ -notlike "*\.local\bin*" }) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $cleanedPath, 'User')
}

# 3. Call Linux uninstall inside WSL
$wslCmd = Get-Command "wsl.exe" -ErrorAction SilentlyContinue
if ($wslCmd) {
    wsl.exe -e bash -c "
        rm -rf ~/.local/share/safi-cli
        rm -f ~/.local/bin/safi-cli ~/.local/bin/saficli ~/.local/bin/sys-exec ~/.local/bin/safi-setup-key
        rm -rf ~/.config/safi
        rm -rf ~/.safi
        [ -d ~/.config ] && [ -z \"\$(ls -A ~/.config 2>/dev/null)\" ] && rmdir ~/.config 2>/dev/null || true
        [ -d ~/.local/bin ] && [ -z \"\$(ls -A ~/.local/bin 2>/dev/null)\" ] && rmdir ~/.local/bin 2>/dev/null || true
        [ -d ~/.local ] && [ -z \"\$(ls -A ~/.local 2>/dev/null)\" ] && rmdir ~/.local 2>/dev/null || true
    " 2>$null
    Write-Host "Removed Linux binaries, runtime, and configuration from WSL." -ForegroundColor Gray
}

Write-Host ""
Write-Host "✓ SAFi CLI and all user configuration (.config, .local, .safi) have been completely removed." -ForegroundColor Green
