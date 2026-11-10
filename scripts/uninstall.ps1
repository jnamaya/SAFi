# SAFi Windows PowerShell Uninstaller
# Cleans up Windows bridges, wrappers, and the WSL Linux installation

param (
    [switch]$Purge
)

Write-Host "=== SAFi CLI Windows Uninstaller ===" -ForegroundColor Cyan

# 1. Remove Windows command wrappers
$wrapperPaths = @(
    "$env:LOCALAPPDATA\Microsoft\WindowsApps\safi-cli.cmd",
    "$env:LOCALAPPDATA\Microsoft\WindowsApps\saficli.cmd",
    "$env:LOCALAPPDATA\Microsoft\WindowsApps\sys-exec.cmd",
    "$env:LOCALAPPDATA\Microsoft\WindowsApps\safi-setup-key.cmd",
    "$env:USERPROFILE\.local\bin\safi-cli.cmd",
    "$env:USERPROFILE\.local\bin\saficli.cmd",
    "$env:USERPROFILE\.local\bin\sys-exec.cmd",
    "$env:USERPROFILE\.local\bin\safi-setup-key.cmd"
)

foreach ($file in $wrapperPaths) {
    if (Test-Path $file) {
        Remove-Item -Force $file -ErrorAction SilentlyContinue
        Write-Host "Removed $file" -ForegroundColor Gray
    }
}

# 2. Call Linux uninstall inside WSL
$wslCmd = Get-Command "wsl.exe" -ErrorAction SilentlyContinue
if ($wslCmd) {
    $purgeFlag = if ($Purge) { "--purge" } else { "" }
    wsl.exe -e bash -c "
        rm -rf ~/.local/share/safi-cli
        rm -f ~/.local/bin/safi-cli ~/.local/bin/saficli ~/.local/bin/sys-exec ~/.local/bin/safi-setup-key
        if [ '$purgeFlag' = '--purge' ]; then
            rm -rf ~/.config/safi
        fi
    " 2>$null
    Write-Host "Removed Linux binaries and runtime from WSL." -ForegroundColor Gray
}

Write-Host "✓ SAFi CLI has been completely uninstalled from Windows." -ForegroundColor Green
if (-not $Purge) {
    Write-Host "Note: Configuration was preserved in WSL ~/.config/safi. Pass -Purge to remove it." -ForegroundColor Yellow
}
