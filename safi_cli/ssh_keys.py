"""SSH key management and deployment helper for SAFi managed infrastructure."""

import base64
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from . import config, ui


def get_default_key_paths() -> tuple[Path, Path]:
    """Return paths to (private_key, public_key) in ~/.ssh/."""
    ssh_dir = Path.home() / ".ssh"
    return ssh_dir / "id_ed25519", ssh_dir / "id_ed25519.pub"


def find_setup_script() -> Optional[Path]:
    """Locate the setup_ssh_key.sh script or safi-setup-key binary."""
    pkg_script = Path(__file__).resolve().parent / "setup_ssh_key.sh"
    if pkg_script.is_file() and os.access(pkg_script, os.X_OK):
        return pkg_script

    repo_script = Path(__file__).resolve().parent.parent / "scripts" / "setup_ssh_key.sh"
    if repo_script.is_file() and os.access(repo_script, os.X_OK):
        return repo_script

    installed_script = Path.home() / ".local" / "share" / "safi-cli" / "setup_ssh_key.sh"
    if installed_script.is_file() and os.access(installed_script, os.X_OK):
        return installed_script

    bin_script = Path.home() / ".local" / "bin" / "safi-setup-key"
    if bin_script.is_file() and os.access(bin_script, os.X_OK):
        return bin_script

    which_bin = shutil.which("safi-setup-key")
    if which_bin:
        return Path(which_bin)

    return None


def ensure_local_ssh_key() -> str:
    """Ensure a local Ed25519 SSH key pair exists and return its public key content."""
    priv_path, pub_path = get_default_key_paths()
    ssh_dir = priv_path.parent

    if not pub_path.is_file():
        ui.console.print(f"[dim]No Ed25519 key found at {pub_path}. Generating new key pair...[/dim]")
        ssh_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            hostname = socket.gethostname()
        except Exception:
            hostname = "local"
        comment = f"safi-agent@{hostname}"
        cmd = ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(priv_path), "-C", comment]
        res = subprocess.call(cmd)
        if res != 0 or not pub_path.is_file():
            raise RuntimeError(f"Failed to generate Ed25519 SSH key at {priv_path}")
        ui.console.print(f"[bold green]✓ Created new Ed25519 key:[/] {pub_path}")

    key_content = pub_path.read_text(encoding="utf-8").strip()
    if not key_content:
        raise ValueError(f"Public key at {pub_path} is empty.")
    return key_content


def build_windows_ps_script(key_content: str) -> str:
    """Build the PowerShell snippet for Windows OpenSSH authorized_keys with strict ACLs."""
    escaped_key = key_content.replace("'", "''")
    return f"""$ErrorActionPreference = 'Stop'
$key = '{escaped_key}'
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$userLower = $env:USERNAME.ToLower()

if ($isAdmin -or $userLower -eq 'administrator') {{
    $adminDir = "$env:ProgramData\\ssh"
    if (!(Test-Path $adminDir)) {{ New-Item -ItemType Directory -Force -Path $adminDir | Out-Null }}
    $adminFile = "$adminDir\\administrators_authorized_keys"
    $existing = if (Test-Path $adminFile) {{ Get-Content -Raw $adminFile }} else {{ "" }}
    if ($existing -notmatch [regex]::Escape($key.Trim())) {{
        Add-Content -Force -Path $adminFile -Value $key.Trim()
    }}
    & icacls.exe $adminFile /inheritance:r /grant "Administrators:F" "SYSTEM:F" | Out-Null
    Write-Host "[SAFI_WIN] Installed in $adminFile with strict ACLs"
}} else {{
    $userDir = "$env:USERPROFILE\\.ssh"
    if (!(Test-Path $userDir)) {{ New-Item -ItemType Directory -Force -Path $userDir | Out-Null }}
    $userFile = "$userDir\\authorized_keys"
    $existing = if (Test-Path $userFile) {{ Get-Content -Raw $userFile }} else {{ "" }}
    if ($existing -notmatch [regex]::Escape($key.Trim())) {{
        Add-Content -Force -Path $userFile -Value $key.Trim()
    }}
    & icacls.exe $userFile /inheritance:r /grant "$($env:USERNAME):F" "SYSTEM:F" | Out-Null
    Write-Host "[SAFI_WIN] Installed in $userFile with strict ACLs"
}}
"""


def deploy_key_native(
    target: str,
    user_override: Optional[str] = None,
    port_override: Optional[int] = None,
    force_os: Optional[str] = None,
) -> int:
    """Deploy SSH key natively using Python and standard SSH tools without external script dependencies."""
    priv_path, pub_path = get_default_key_paths()

    try:
        key_content = ensure_local_ssh_key()
    except Exception as exc:
        ui.print_error(f"SSH key preparation failed: {exc}")
        return 1

    ui.console.print(f"\n[bold {ui.COLOR_BRAND_400}]=== SAFi SSH Key Deployment ===[/]")
    ui.console.print(f"  [dim]Local Public Key:[/] {pub_path}")

    # Resolve target from inventory or direct user@host
    inventory = config.load_inventory()
    host = ""
    user = ""
    port = 22
    os_type = "linux"
    is_inventory = False

    if target in inventory:
        is_inventory = True
        item = inventory[target]
        host = str(item.get("host", "")).replace("ssh ", "").strip()
        user = str(item.get("user", "")).strip() if item.get("user") else ""
        try:
            port = int(item.get("port", 22))
        except (ValueError, TypeError):
            port = 22
        desc = str(item.get("description", "")).lower()
        cfg_os = str(item.get("os", "")).lower()
        if "win" in cfg_os or "win" in desc or "win" in target.lower():
            os_type = "windows"
        else:
            os_type = "linux"
        ui.console.print(f"  [dim]Resolved from inventory:[/] [bold]{target}[/] -> {user or os.environ.get('USER')}@{host}:{port} ({os_type})")
    elif "@" in target:
        user, host = target.split("@", 1)
        os_type = "linux"
    else:
        host = target
        os_type = "linux"

    if user_override:
        user = user_override
    if port_override:
        port = port_override
    if force_os:
        os_type = force_os.lower()

    if not user:
        user = os.environ.get("USER") or os.environ.get("USERNAME") or "root"

    ui.console.print(f"  [dim]Target Connection:[/]  [bold white]{user}@{host}[/] (port {port}, os: {os_type})\n")

    # Step 1: Check existing passwordless connection
    ui.console.print("[dim]Checking existing passwordless connectivity... [/dim]", end="")
    check_cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=4",
        "-p", str(port),
        f"{user}@{host}",
        "echo OK",
    ]
    try:
        res = subprocess.run(check_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if res.returncode == 0:
            ui.console.print(f"[bold {ui.COLOR_PASS}]ALREADY CONFIGURED ✓[/]")
            ui.console.print(f"SSH key authentication is already working for {user}@{host}.")
            if is_inventory:
                ui.console.print(f"You can run commands using: [cyan]sys-exec {target} <command>[/]\n")
            return 0
    except Exception:
        pass

    ui.console.print("[dim yellow]needs installation.[/dim yellow]")

    # Step 2: Deploy key
    if os_type == "windows":
        ui.console.print("\n[bold]Configuring Windows OpenSSH Server...[/]")
        ui.console.print("[dim]Windows OpenSSH requires strict NTFS permissions (ACLs) via icacls.[/dim]")
        ui.console.print(f"[bold yellow]You will be prompted for {user}@{host}'s password once:[/]")

        ps_script = build_windows_ps_script(key_content)
        b64_ps = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")

        ssh_cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=accept-new",
            "-p", str(port),
            f"{user}@{host}",
            f"powershell.exe -NoProfile -NonInteractive -EncodedCommand {b64_ps}",
        ]
        ret = subprocess.call(ssh_cmd, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
        if ret != 0:
            ui.print_error(f"Failed to deploy key to Windows target {user}@{host} (exit code {ret}).")
            return ret
    else:
        ui.console.print("\n[bold]Installing key to Linux host...[/]")
        ui.console.print(f"[bold yellow]You will be prompted for {user}@{host}'s password once:[/]")

        if shutil.which("ssh-copy-id"):
            copy_cmd = [
                "ssh-copy-id",
                "-o", "StrictHostKeyChecking=accept-new",
                "-i", str(pub_path),
                "-p", str(port),
                f"{user}@{host}",
            ]
            ret = subprocess.call(copy_cmd, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
        else:
            remote_sh = (
                f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
                f"(grep -qF '{key_content}' ~/.ssh/authorized_keys 2>/dev/null || echo '{key_content}' >> ~/.ssh/authorized_keys) && "
                f"chmod 600 ~/.ssh/authorized_keys"
            )
            fallback_cmd = [
                "ssh",
                "-o", "StrictHostKeyChecking=accept-new",
                "-p", str(port),
                f"{user}@{host}",
                remote_sh,
            ]
            ret = subprocess.call(fallback_cmd, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)

        if ret != 0:
            ui.print_error(f"Failed to deploy key to Linux target {user}@{host} (exit code {ret}).")
            return ret

    # Step 3: Final Verification
    ui.console.print("\n[dim]Verifying passwordless SSH connection... [/dim]", end="")
    verify_cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=5",
        "-p", str(port),
        f"{user}@{host}",
        "echo OK",
    ]
    try:
        vres = subprocess.run(verify_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if vres.returncode == 0:
            ui.console.print(f"[bold {ui.COLOR_PASS}]SUCCESS! ✓[/]")
            ui.console.print("=" * 60)
            ui.console.print(f"[bold green]✓ Key authentication successfully configured for {user}@{host}[/]")
            ui.console.print("=" * 60)
            if is_inventory:
                ui.console.print(f"\nTarget '[bold]{target}[/]' is now ready for autonomous execution:")
                ui.console.print(f"   [cyan]sys-exec {target} \"uptime\"[/]\n")
            return 0
        else:
            ui.console.print(f"[bold {ui.COLOR_FAIL}]FAILED[/]")
            ui.print_error(f"Could not connect passwordlessly after installation to {user}@{host}.")
            return 1
    except Exception as exc:
        ui.print_error(f"Verification check failed: {exc}")
        return 1


def run_setup_key(args: List[str]) -> int:
    """Parse arguments and deploy SSH key natively."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="safi setup-key",
        description="Deploy SSH public key to Linux or Windows inventory target or remote host.",
    )
    parser.add_argument("target", nargs="?", help="Inventory target alias (e.g. local-VM, win-server) or user@host")
    parser.add_argument("-p", "--port", type=int, help="SSH port")
    parser.add_argument("-u", "--user", help="Remote user")
    parser.add_argument("--win", "--windows", dest="win", action="store_true", help="Force Windows OpenSSH setup")
    parser.add_argument("--linux", dest="linux", action="store_true", help="Force Linux OpenSSH setup")

    parsed, unknown = parser.parse_known_args(args)

    if not parsed.target:
        interactive_setup_key()
        return 0

    force_os = "windows" if parsed.win else ("linux" if parsed.linux else None)
    return deploy_key_native(
        target=parsed.target,
        user_override=parsed.user,
        port_override=parsed.port,
        force_os=force_os,
    )


def interactive_setup_key(target_arg: Optional[str] = None) -> None:
    """Interactive command handler for /setup-key [target]."""
    inventory = config.load_inventory()

    if target_arg and target_arg.strip():
        run_setup_key([target_arg.strip()])
        return

    ui.console.print(f"\n[bold {ui.COLOR_BRAND_400}]🔑 Deploy SSH Key to Server[/]")
    ui.console.print("[dim]Pushes your local Ed25519 public key to Linux or Windows targets for passwordless execution.[/dim]\n")

    if not inventory:
        ui.console.print(f"[{ui.COLOR_WARN}]No targets found in {config.INVENTORY_FILE}.[/]")
        try:
            target = input("Enter target (user@host or hostname): ").strip()
        except (KeyboardInterrupt, EOFError):
            return
        if target:
            run_setup_key([target])
        return

    from rich import box
    from rich.table import Table

    table = Table(box=box.ROUNDED, border_style=ui.COLOR_BRAND_600)
    table.add_column("#", style="dim", width=4)
    table.add_column("Alias", style=f"bold {ui.COLOR_BRAND_400}")
    table.add_column("Host", style="bold white")
    table.add_column("User", style="cyan")
    table.add_column("OS / Description", style="dim")

    target_keys = list(inventory.keys())
    for idx, key in enumerate(target_keys, 1):
        item = inventory[key]
        host = item.get("host", "")
        user = item.get("user", "(ssh-config)")
        desc = item.get("description", item.get("os", "linux"))
        table.add_row(str(idx), key, str(host), str(user), str(desc))

    ui.console.print(table)
    ui.console.print(f"[dim]Enter a number (1-{len(target_keys)}), an alias, or custom user@host (Ctrl+C to cancel):[/dim]")

    try:
        choice = input("Target: ").strip()
    except (KeyboardInterrupt, EOFError):
        ui.console.print()
        return

    if not choice:
        return

    target = choice
    if choice.isdigit() and 1 <= int(choice) <= len(target_keys):
        target = target_keys[int(choice) - 1]

    ui.console.print(f"\n[bold {ui.COLOR_BRAND_500}]Connecting to deploy SSH key to '{target}'...[/]")
    run_setup_key([target])


def main():
    """Standalone CLI entry point for safi-setup-key."""
    args = sys.argv[1:]
    try:
        code = run_setup_key(args)
        sys.exit(code if isinstance(code, int) else 0)
    except KeyboardInterrupt:
        ui.console.print("\n[dim]SSH key setup cancelled.[/dim]")
        sys.exit(130)


if __name__ == "__main__":
    main()
