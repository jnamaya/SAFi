from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

from . import __version__, ui

INSTALL_SH_URL = os.environ.get("SAFI_CLI_INSTALL_URL", "https://runsafi.com/install.sh")


def _parse_version(raw: str) -> Tuple[int, ...]:
    nums = [int(p) for p in re.findall(r"\d+", str(raw or ""))]
    return tuple(nums) if nums else (0,)


def is_newer_version(latest: str, current: str = __version__) -> bool:
    if not latest:
        return False
    return _parse_version(latest) > _parse_version(current)


def check_for_update(client) -> Optional[Tuple[str, str]]:
    if os.environ.get("SAFI_CLI_NO_UPDATE_CHECK", "").strip().lower() in ("1", "true", "yes"):
        return None
    try:
        cfg = client.get_app_config()
    except Exception:
        return None
    if not isinstance(cfg, dict):
        return None
    latest = str(cfg.get("latest_cli_version") or "").strip()
    if latest and is_newer_version(latest, __version__):
        return (__version__, latest)
    return None


def print_update_notice_if_available(client) -> None:
    update = check_for_update(client)
    if not update:
        return
    current_ver, latest_ver = update
    ui.console.print(
        f"[bold {ui.COLOR_WARN}]Update available:[/] safi {current_ver} -> [bold {ui.COLOR_PASS}]{latest_ver}[/] "
        f"[dim](run [bold]safi update[/] or [bold]/update[/])[/]"
    )


def _find_git_install_root() -> Optional[Path]:
    pkg_dir = Path(__file__).resolve().parent
    candidate = pkg_dir.parent
    if (candidate / ".git").exists() and (candidate / "safi_cli").is_dir():
        return candidate
    return None


def run_self_update() -> int:
    ui.console.print(f"[bold {ui.COLOR_BRAND_400}]SAFi CLI Update[/] [dim](current: v{__version__})[/]")

    git_root = _find_git_install_root()
    if git_root is not None:
        status = subprocess.run(
            ["git", "-C", str(git_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
        )
        if status.returncode == 0 and not status.stdout.strip():
            ui.console.print(f"[dim]Updating git checkout at {git_root}...[/]")
            pull = subprocess.run(["git", "-C", str(git_root), "pull", "--ff-only"])
            if pull.returncode == 0:
                ui.console.print(f"[bold {ui.COLOR_PASS}]✓ SAFi CLI updated. Restart 'safi' to use the new version.[/]")
                return 0
            ui.console.print(f"[{ui.COLOR_WARN}]git pull failed (exit {pull.returncode}); falling back to installer...[/]")
        elif status.returncode == 0 and status.stdout.strip():
            ui.console.print(
                f"[{ui.COLOR_WARN}]Local checkout at {git_root} has uncommitted changes; skipping git pull.[/]"
            )
            return 1

    ui.console.print(f"[dim]Downloading latest installer from {INSTALL_SH_URL}...[/]")
    tmp_path = None
    try:
        req = urllib.request.Request(INSTALL_SH_URL, headers={"User-Agent": f"safi-cli/{__version__}"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            script_bytes = resp.read().replace(b"\r\n", b"\n")
        fd, tmp_path = tempfile.mkstemp(prefix="safi-update-", suffix=".sh")
        with os.fdopen(fd, "wb") as fh:
            fh.write(script_bytes)
        os.chmod(tmp_path, 0o700)
        rc = subprocess.call(["bash", tmp_path])
        if rc == 0:
            ui.console.print(f"\n[bold {ui.COLOR_PASS}]✓ Update complete. Restart 'safi' to load the new version.[/]")
        else:
            ui.print_error(f"Installer exited with code {rc}.")
        return rc
    except Exception as exc:
        ui.print_error(f"Could not download updater from {INSTALL_SH_URL}: {exc}")
        return 1
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
