"""Local repository tools and execution engine for SAFi CLI.

These tools execute directly on the developer's local filesystem in the
current working directory, under SAFi's Will Gate and path confinement.
"""

import fnmatch
import logging
import os
import re
import shutil
import signal
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("safi.tools")

FORBIDDEN_NAMES = frozenset({
    ".env", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
    "authorized_keys", "known_hosts", "credentials", ".netrc", ".pgpass",
    "secrets.json", "inventory.json",
})
FORBIDDEN_DIRS = frozenset({
    ".git", ".ssh", ".aws", ".gnupg", ".kube",
})
FORBIDDEN_SUFFIXES = (
    ".pem", ".key", ".pkcs12", ".pfx", ".p12", ".kdbx", ".jks",
)
# `.env.*` files hold secrets (.env.local, .env.production); these templates do not.
ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")
SKIP_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", ".tox", ".eggs",
    ".cache", "cache", "chroot", "iso", "binary", ".build", "auto",
})
BINARY_EXTENSIONS = frozenset({
    ".iso", ".bin", ".img", ".tar", ".gz", ".xz", ".bz2", ".zip", ".7z",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".pyc", ".pyo", ".so",
    ".dylib", ".dll", ".whl", ".woff", ".woff2", ".ttf", ".eot", ".mp3",
    ".mp4", ".mov", ".db", ".sqlite", ".sqlite3", ".o", ".a", ".class",
})
MAX_GREP_FILE_SIZE = 1_000_000


SOFTWARE_ENGINEER_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read file contents with 1-indexed line numbers. Path is relative to the repository root. Avoid redundant re-reads; use offset/limit to paginate if a file is long.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to repository root."},
                    "offset": {"type": "integer", "description": "1-indexed starting line number (default 1). Alias: line_start."},
                    "limit": {"type": "integer", "description": "Maximum number of lines to read (default 1000)."},
                    "line_start": {"type": "integer", "description": "1-indexed starting line number."},
                    "line_end": {"type": "integer", "description": "1-indexed ending line number."}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write",
            "description": "Create a brand-new file or overwrite an entire file when a full rewrite is needed. Prefer 'edit' for targeted modifications to existing files. Path is relative to the repository root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to repository root."},
                    "content": {"type": "string", "description": "New content to write to the file."}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit",
            "description": "Modify, fix, or update an existing file by replacing an exact contiguous block of text. MANDATORY for targeted changes to existing files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to repository root."},
                    "target": {"type": "string", "description": "Exact contiguous text sequence to replace."},
                    "replacement": {"type": "string", "description": "Replacement text sequence."}
                },
                "required": ["path", "target", "replacement"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete",
            "description": "Delete a file or directory in the repository. Path is relative to the repository root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File or directory path relative to repository root to delete."}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search file contents in the repository using a regular expression.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regular expression pattern to search for."},
                    "path": {"type": "string", "description": "Directory or file path to search in (default '.')."},
                    "include": {"type": "string", "description": "Optional file glob filter, e.g. '*.py'."}
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "Find files matching a glob pattern (e.g. '**/*.py' or 'src/*').",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern (default '*')."},
                    "path": {"type": "string", "description": "Subdirectory to search in (default '.')."}
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list",
            "description": "List files and directories in a repository directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path relative to repository root (default '.')."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command (e.g. pytest, git diff, npm test, python3) in the repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The exact shell command line to execute."}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "task",
            "description": "Delegate READ-ONLY work to an isolated subagent: multi-file exploration/search ('researcher'), running tests ('tester'), or reviewing code ('code_reviewer'). Subagents CANNOT modify files — never delegate implementation, editing, writing, or any file change; do that yourself with edit/write. Returns synthesized findings without consuming main context tokens.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Short 3-5 word summary of the delegated task."},
                    "prompt": {"type": "string", "description": "Detailed goal and instructions for the subagent."},
                    "subagent_type": {
                        "type": "string",
                        "description": "Role for the subagent: 'researcher' (read-only search), 'tester' (test runner), or 'code_reviewer'.",
                        "enum": ["researcher", "tester", "code_reviewer"]
                    }
                },
                "required": ["description", "prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "question",
            "description": "Ask the user a clarifying question ONLY when there is a critical, blocking ambiguity that prevents completing the task. DO NOT use this tool for routine choices, intermediate steps, or to ask permission to continue. Make sensible engineering decisions and execute autonomously.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The specific blocking question to ask the user."},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of recommended choices for the user to select from."
                    }
                },
                "required": ["question"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Get structured git repository status showing branch, staged files, modified files, and untracked files.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Inspect uncommitted code changes in the repository. Optionally specify 'staged' (boolean) or a specific 'path'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "staged": {"type": "boolean", "description": "If true, shows staged changes (--staged). Default false."},
                    "path": {"type": "string", "description": "Optional file or directory path relative to repository root."}
                }
            }
        }
    }
]

SYSADMIN_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run shell and CLI administration commands (e.g. systemctl, journalctl, ssh, sys-exec, docker, ip, df, curl, ps) on the system or remote servers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The exact shell command line to execute."}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read system configuration files, service units, scripts, and logs with 1-indexed line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read."},
                    "offset": {"type": "integer", "description": "1-indexed starting line number (default 1). Alias: line_start."},
                    "limit": {"type": "integer", "description": "Maximum number of lines to read (default 1000)."},
                    "line_start": {"type": "integer", "description": "1-indexed starting line number."},
                    "line_end": {"type": "integer", "description": "1-indexed ending line number."}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write",
            "description": "Create a new configuration file, script, or unit file. Prefer 'edit' for targeted changes to existing configs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to create or write."},
                    "content": {"type": "string", "description": "Content to write to the file."}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit",
            "description": "Modify, update, or patch an existing configuration file or script by replacing an exact contiguous block of text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to modify."},
                    "target": {"type": "string", "description": "Exact contiguous text sequence to replace."},
                    "replacement": {"type": "string", "description": "Replacement text sequence."}
                },
                "required": ["path", "target", "replacement"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete",
            "description": "Delete an obsolete configuration file, temporary file, or directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File or directory path to delete."}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search configuration files, scripts, or system logs using regular expressions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regular expression pattern to search for."},
                    "path": {"type": "string", "description": "Directory or file path to search in (default '.')."},
                    "include": {"type": "string", "description": "Optional file glob filter, e.g. '*.conf', '*.service'."}
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "Find configuration files, service units, or logs matching a glob pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern (default '*')."},
                    "path": {"type": "string", "description": "Subdirectory to search in (default '.')."}
                },
                "required": ["pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list",
            "description": "List files and directories in a directory path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default '.')."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "question",
            "description": "Ask the operator a clarifying question ONLY when there is a critical, blocking operational ambiguity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The specific blocking question to ask the operator."},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of recommended choices."
                    }
                },
                "required": ["question"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "m365_admin",
            "description": "Govern and manage Microsoft 365 and Entra ID (Azure AD): list/get users, reset user passwords, audit licenses, assign/revoke license SKUs, list security groups, and view sign-in audit logs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "The administrative action to perform.",
                        "enum": [
                            "list_users",
                            "get_user",
                            "reset_password",
                            "list_licenses",
                            "assign_license",
                            "revoke_license",
                            "list_groups",
                            "get_sign_ins"
                        ]
                    },
                    "params": {
                        "type": "object",
                        "description": "Action-specific parameters: 'user_id' (UPN/email), 'temp_password', 'force_change' (bool), 'sku_id', 'query' (search filter), 'limit' (int)."
                    },
                    "tenant": {
                        "type": "string",
                        "description": "Optional tenant alias from cloud config. Defaults to primary tenant."
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "azure_admin",
            "description": "Govern and operate Azure cloud resources: list resource groups, list virtual machines, check VM status/instanceView, perform VM actions (start, stop, restart, deallocate), and discover cloud resources.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "The Azure administrative action to perform.",
                        "enum": [
                            "list_resource_groups",
                            "list_vms",
                            "get_vm",
                            "vm_action",
                            "list_resources"
                        ]
                    },
                    "params": {
                        "type": "object",
                        "description": "Action-specific parameters: 'resource_group', 'vm_name', 'action' (start/stop/restart/deallocate), 'resource_type'."
                    },
                    "subscription": {
                        "type": "string",
                        "description": "Optional subscription alias from cloud config. Defaults to primary subscription."
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cloud_status",
            "description": "Inspect the status, connectivity, and configured tenants/subscriptions for Microsoft 365 and Azure environments.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]

# Default / backward compatibility alias
TOOL_SCHEMAS: List[Dict[str, Any]] = SOFTWARE_ENGINEER_TOOL_SCHEMAS


def get_tools_for_agent(agent: Optional[str]) -> List[Dict[str, Any]]:
    """Return the designated tool schemas for the given agent."""
    if not agent:
        return []
    low = agent.lower()
    if low in ("fiduciary", "the_fiduciary", "health_navigator", "socratic_tutor", "bible_scholar", "safi_steward"):
        return []
    if "sysadmin" in low:
        return list(SYSADMIN_TOOL_SCHEMAS)
    if (
        "software_engineer" in low
        or "engineer" in low
        or "coding" in low
        or "red_team" in low
        or "security" in low
        or "operator" in low
        or "adversarial" in low
    ):
        return list(SOFTWARE_ENGINEER_TOOL_SCHEMAS)
    # Default fallback for any custom or unlisted agent connected through the CLI harness:
    # Offer the harness tools so the client advertises them; the server's WillGate
    # policy remains the authoritative enforcement layer.
    return list(SOFTWARE_ENGINEER_TOOL_SCHEMAS)


def _is_secret_name(name: str) -> bool:
    """True for credential files: exact names, key suffixes, and .env.* variants (templates excepted)."""
    lower = name.lower()
    if lower in FORBIDDEN_NAMES or any(lower.endswith(s) for s in FORBIDDEN_SUFFIXES):
        return True
    if lower.startswith(".env.") and not lower.endswith(ENV_TEMPLATE_SUFFIXES):
        return True
    return False


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def resolve_safe_path(rel_path: str, workspace_root: Path, *, follow_symlinks: bool = True) -> Path:
    """Confine a relative path to workspace_root and block protected directories and secret files."""
    ws_resolved = workspace_root.resolve()
    raw_target = workspace_root / rel_path

    if follow_symlinks:
        target = raw_target.resolve()
    else:
        target = raw_target.parent.resolve() / raw_target.name

    try:
        rel_parts = target.relative_to(ws_resolved).parts
    except ValueError:
        raise PermissionError(f"Access denied: '{rel_path}' resolves outside the repository root.")

    raw_norm_parts = Path(os.path.normpath(rel_path)).parts
    for part in set(rel_parts) | set(raw_norm_parts):
        if part.lower() in FORBIDDEN_DIRS:
            raise PermissionError(f"Access denied: '{part}' is a protected directory and cannot be accessed directly.")
        if _is_secret_name(part):
            raise PermissionError(f"Access denied: '{part}' is a secret/credential file and cannot be accessed.")

    return target


def _dir_contains_protected(directory: Path) -> Optional[str]:
    """Return the name of any protected directory or secret file inside `directory`, else None."""
    for root, dirs, files in os.walk(directory, followlinks=False):
        for d in dirs:
            if d.lower() in FORBIDDEN_DIRS or _is_secret_name(d):
                return d
        for f in files:
            if _is_secret_name(f):
                return f
    return None


def _build_bwrap_command(
    cmd: str,
    workspace_root: Path,
    agent: Optional[str] = None,
) -> Optional[List[str]]:
    """Build a Bubblewrap (bwrap) isolation command for running bash commands safely.

    Sandboxes execution:
    - Root filesystem is mounted read-only (--ro-bind / /).
    - Workspace is mounted read-write (--bind ws ws).
    - /tmp is a private in-memory filesystem (--tmpfs /tmp).
    - Process namespace is unshared (--unshare-pid).
    - Session is isolated (--new-session) to prevent terminal injection (TIOCSTI ioctl attacks).
    - For non-sysadmin agents, sensitive credential directories (~/.ssh, ~/.config/safi,
      ~/.aws, ~/.azure, ~/.gnupg, ~/.kube, ~/.docker, ~/.config/gh) and shell histories / auth tokens
      are masked with empty tmpfs or /dev/null mounts.
    """
    bwrap_path = shutil.which("bwrap")
    if not bwrap_path:
        logger.warning(
            "Bubblewrap (bwrap) binary not found on PATH. Commands will execute unconfined on the host."
        )
        return None

    ws = str(workspace_root.resolve())
    bwrap_cmd = [
        bwrap_path,
        "--ro-bind", "/", "/",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
        "--unshare-pid",
        "--new-session",
        "--die-with-parent",
        "--bind", ws, ws,
        "--chdir", ws,
    ]

    home = Path.home().resolve()
    is_sysadmin = agent is not None and "sysadmin" in agent.lower()

    if not is_sysadmin:
        sensitive_dirs = [
            home / ".ssh",
            home / ".config" / "safi",
            home / ".config" / "gh",
            home / ".aws",
            home / ".azure",
            home / ".gnupg",
            home / ".kube",
            home / ".docker",
            home / ".local" / "share" / "keyrings",
        ]
        for sdir in sensitive_dirs:
            if sdir.exists() and sdir.is_dir():
                bwrap_cmd.extend(["--tmpfs", str(sdir)])

        sensitive_files = [
            home / ".bash_history",
            home / ".zsh_history",
            home / ".netrc",
            home / ".git-credentials",
            home / ".npmrc",
            home / ".pypirc",
        ]
        for sfile in sensitive_files:
            if sfile.exists():
                bwrap_cmd.extend(["--ro-bind-try", "/dev/null", str(sfile)])

        # Allow read-only access to known_hosts and ssh config so git/ssh can verify
        # remote host identities (e.g. github.com) and use ssh configs without exposing any private key files.
        ssh_dir = home / ".ssh"
        if ssh_dir.exists() and ssh_dir.is_dir():
            bwrap_cmd.extend([
                "--ro-bind-try", str(ssh_dir / "known_hosts"), str(ssh_dir / "known_hosts"),
                "--ro-bind-try", str(ssh_dir / "known_hosts.old"), str(ssh_dir / "known_hosts.old"),
                "--ro-bind-try", str(ssh_dir / "config"), str(ssh_dir / "config"),
            ])

    bwrap_cmd.extend(["bash", "-c", cmd])
    return bwrap_cmd


def execute_tool(
    name: str,
    args: Dict[str, Any],
    workspace_root: Path,
    agent: Optional[str] = None,
    on_output: Optional[Callable[[str], None]] = None,
) -> str:
    """Execute a tool proposal locally inside workspace_root."""
    try:
        if agent:
            allowed_tools = {t["function"]["name"] for t in get_tools_for_agent(agent)}
            if allowed_tools and name not in allowed_tools:
                return f"Error: Tool '{name}' is not authorized for agent '{agent}'."

        if name == "read":
            path_str = args.get("path") or args.get("filePath") or args.get("file_path") or ""
            if not path_str.strip():
                return "Error: 'path' parameter is required for read."
            target = resolve_safe_path(path_str, workspace_root)
            if not target.exists():
                return f"Error: No such file: {path_str}"
            if target.is_dir():
                return f"Error: {path_str} is a directory. Use list instead."

            raw_start = args.get("offset") or args.get("line_start") or args.get("start_line") or args.get("startLine")
            raw_end = args.get("line_end") or args.get("end_line") or args.get("endLine")
            raw_limit = args.get("limit")

            offset = max(1, _safe_int(raw_start, 1))
            if raw_end is not None:
                calc_limit = max(1, _safe_int(raw_end, offset) - offset + 1)
                limit = min(calc_limit, 2000)
            elif raw_limit is not None:
                limit = max(1, min(_safe_int(raw_limit, 1000), 2000))
            else:
                limit = 1000

            with target.open("r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()

            total = len(lines)
            if total == 0:
                return "(empty file)"
            if offset > total:
                return f"Error: offset {offset} is past end of file ({total} lines total)."

            slice_lines = lines[offset - 1 : offset - 1 + limit]
            max_read_chars = 18_000
            rendered_lines: List[str] = []
            used_chars = 0
            for i, line in enumerate(slice_lines):
                entry = f"{offset + i}: {line}"
                if rendered_lines and used_chars + len(entry) > max_read_chars:
                    break
                rendered_lines.append(entry)
                used_chars += len(entry)
            body = "".join(rendered_lines)
            last_line = offset - 1 + len(rendered_lines)
            truncated = last_line < total
            note = (
                f"\n... [file truncated at line {last_line} of {total} lines total. "
                f"Use read(path='{path_str}', offset={last_line + 1}, limit=300) or grep if you need lines after {last_line}.]"
                if truncated else ""
            )
            return body + note

        elif name == "write":
            path_str = args.get("path") or args.get("filePath") or args.get("file_path") or ""
            if not path_str.strip():
                return "Error: 'path' parameter is required for write."
            content = str(args.get("content") if args.get("content") is not None else "")
            if path_str.endswith("scratchpad.md") and "\\n" in content and "\n" not in content:
                content = content.replace("\\n", "\n")
            target = resolve_safe_path(path_str, workspace_root)
            if target == workspace_root.resolve() or target.is_dir():
                return f"Error: Cannot write to directory '{path_str}'. Specify a target file path."
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} characters to {path_str}."

        elif name == "edit":
            path_str = args.get("path") or args.get("filePath") or args.get("file_path") or ""
            if not path_str.strip():
                return "Error: 'path' parameter is required for edit."
            target_str = (
                args.get("target")
                or args.get("oldString")
                or args.get("old_string")
                or args.get("old_str")
                or args.get("oldText")
                or ""
            )
            replacement_str = (
                args.get("replacement")
                or args.get("newString")
                or args.get("new_string")
                or args.get("new_str")
                or args.get("newText")
                or ""
            )
            if not target_str:
                return f"Error: 'target' text is required for edit. Use 'write' to create or rewrite {path_str}."
            target = resolve_safe_path(path_str, workspace_root)
            if not target.exists():
                return f"Error: No such file: {path_str}"

            text = target.read_text(encoding="utf-8", errors="replace")
            count = text.count(target_str)
            if count == 0:
                normalized_text = text.replace("\r\n", "\n")
                normalized_target = target_str.replace("\r\n", "\n")
                normalized_replacement = replacement_str.replace("\r\n", "\n")
                if normalized_target in normalized_text and normalized_text.count(normalized_target) == 1:
                    new_text = normalized_text.replace(normalized_target, normalized_replacement, 1)
                    target.write_text(new_text, encoding="utf-8")
                    return f"Successfully applied edit to {path_str}."
                if "\\n" in normalized_target and "\n" not in normalized_target:
                    unescaped_target = normalized_target.replace("\\n", "\n")
                    unescaped_replacement = normalized_replacement.replace("\\n", "\n")
                    if unescaped_target in normalized_text and normalized_text.count(unescaped_target) == 1:
                        new_text = normalized_text.replace(unescaped_target, unescaped_replacement, 1)
                        target.write_text(new_text, encoding="utf-8")
                        return f"Successfully applied edit to {path_str}."
                return f"Error: Target text block not found in {path_str}. Verify whitespace and indentation, or use 'write' to rewrite the full file."
            if count > 1:
                return f"Error: Target text occurs {count} times in {path_str}. Provide more surrounding lines for uniqueness, or use 'write' to rewrite the full file."

            new_text = text.replace(target_str, replacement_str, 1)
            target.write_text(new_text, encoding="utf-8")
            return f"Successfully applied edit to {path_str}."

        elif name in ("delete", "remove"):
            path_str = args.get("path") or args.get("filePath") or args.get("file_path") or ""
            if not path_str.strip():
                return "Error: 'path' parameter is required for delete."
            target = resolve_safe_path(path_str, workspace_root, follow_symlinks=False)
            if not target.exists() and not target.is_symlink():
                return f"Error: No such file or directory: {path_str}"
            if target == workspace_root.resolve():
                return "Error: Cannot delete the repository root directory."
            if target.is_symlink() or target.is_file():
                target.unlink()
                return f"Successfully deleted file: {path_str}"
            elif target.is_dir():
                protected_item = _dir_contains_protected(target)
                if protected_item:
                    raise PermissionError(
                        f"Access denied: Cannot delete directory '{path_str}' because it contains protected item '{protected_item}'."
                    )
                shutil.rmtree(target)
                return f"Successfully deleted directory: {path_str}"
            return f"Error: Cannot delete '{path_str}'."

        elif name == "grep":
            pattern = args.get("pattern") or ""
            sub_path = args.get("path") or "."
            include = args.get("include")
            search_dir = resolve_safe_path(sub_path, workspace_root)
            if not search_dir.exists():
                return f"Error: Path does not exist: {sub_path}"

            max_matches = 100

            if (workspace_root / ".git").is_dir():
                try:
                    cmd = ["git", "grep", "--untracked", "-n", "-I", "-E", "-e", pattern, "--"]
                    base = "" if sub_path in (".", "./", "") else sub_path.rstrip("/")
                    if include:
                        glob_pat = include if any(c in include for c in "*?[") else f"*{include}"
                        cmd.append(f":(glob){base + '/' if base else ''}**/{glob_pat}")
                    elif base:
                        cmd.append(base)
                    proc = subprocess.run(
                        cmd,
                        cwd=str(workspace_root),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=5,
                    )
                    if proc.returncode == 0:
                        lines = [
                            l for l in proc.stdout.splitlines()
                            if l.strip() and not _is_secret_name(Path(l.split(":", 1)[0]).name)
                        ]
                        if not lines:
                            return f"No matches found for pattern: '{pattern}'"
                        if len(lines) > max_matches:
                            return "\n".join(lines[:max_matches]) + f"\n... [reached {max_matches} match limit]"
                        return "\n".join(lines)
                    elif proc.returncode == 1:
                        return f"No matches found for pattern: '{pattern}'"
                except Exception as exc:
                    logger.warning("ripgrep fallback failed for pattern %r: %s", pattern, exc)

            try:
                regex = re.compile(pattern, re.IGNORECASE)
            except re.error:
                regex = None
            matches: List[str] = []

            for dirpath, dirnames, filenames in os.walk(search_dir):
                dirnames[:] = [
                    d for d in sorted(dirnames)
                    if d not in SKIP_DIRS and d.lower() not in FORBIDDEN_DIRS and not d.startswith(".")
                ]
                for f in sorted(filenames):
                    if f.startswith(".") or _is_secret_name(f):
                        continue
                    if any(f.lower().endswith(ext) for ext in BINARY_EXTENSIONS):
                        continue
                    if include and not fnmatch.fnmatch(f, include):
                        continue
                    file_path = Path(dirpath) / f
                    try:
                        if file_path.stat().st_size > MAX_GREP_FILE_SIZE:
                            continue
                        rel = file_path.relative_to(workspace_root.resolve()).as_posix()
                        with file_path.open("r", encoding="utf-8", errors="replace") as fh:
                            for idx, line in enumerate(fh, start=1):
                                matched = regex.search(line) if regex else (pattern.lower() in line.lower())
                                if matched:
                                    matches.append(f"{rel}:{idx}: {line.strip()[:200]}")
                                    if len(matches) >= max_matches:
                                        return "\n".join(matches) + f"\n... [reached {max_matches} match limit]"
                    except (OSError, PermissionError):
                        continue

            if not matches:
                return f"No matches found for pattern: '{pattern}'"
            return "\n".join(matches)

        elif name == "glob":
            pattern = args.get("pattern") or "*"
            sub_path = args.get("path") or "."
            search_dir = resolve_safe_path(sub_path, workspace_root)
            if not search_dir.exists():
                return f"Error: Path does not exist: {sub_path}"

            matched_files: List[str] = []
            for dirpath, dirnames, filenames in os.walk(search_dir):
                dirnames[:] = [
                    d for d in sorted(dirnames)
                    if d not in SKIP_DIRS and d.lower() not in FORBIDDEN_DIRS and not d.startswith(".")
                ]
                for f in sorted(filenames):
                    if f.startswith(".") or _is_secret_name(f):
                        continue
                    if any(f.lower().endswith(ext) for ext in BINARY_EXTENSIONS):
                        continue
                    file_path = Path(dirpath) / f
                    try:
                        rel = file_path.relative_to(workspace_root.resolve()).as_posix()
                        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(f, pattern):
                            matched_files.append(rel)
                            if len(matched_files) >= 200:
                                return "\n".join(matched_files) + "\n... [limit reached]"
                    except (OSError, PermissionError):
                        continue
            return "\n".join(matched_files) if matched_files else "No files matched."

        elif name == "list":
            sub_path = args.get("path") or "."
            target = resolve_safe_path(sub_path, workspace_root)
            if not target.exists():
                return f"Error: Path does not exist: {sub_path}"
            if not target.is_dir():
                return f"Error: {sub_path} is a file, not a directory."

            entries = []
            for item in sorted(target.iterdir()):
                if (
                    item.name.startswith(".")
                    or item.name in SKIP_DIRS
                    or item.name.lower() in FORBIDDEN_DIRS
                    or _is_secret_name(item.name)
                ):
                    continue
                suffix = "/" if item.is_dir() else ""
                entries.append(f"{item.name}{suffix}")
            return "\n".join(entries) if entries else "(empty directory)"

        elif name == "bash":
            cmd = args.get("command") or ""
            is_sysadmin = agent is not None and "sysadmin" in agent.lower()
            bash_timeout = 420 if is_sysadmin else 120
            clean_env = os.environ.copy()
            if not is_sysadmin:
                for k in (
                    "ANTHROPIC_API_KEY",
                    "OPENAI_API_KEY",
                    "GEMINI_API_KEY",
                    "AWS_ACCESS_KEY_ID",
                    "AWS_SECRET_ACCESS_KEY",
                    "AWS_SESSION_TOKEN",
                    "GITHUB_TOKEN",
                    "GH_TOKEN",
                ):
                    clean_env.pop(k, None)

            bwrap_cmd = _build_bwrap_command(cmd, workspace_root, agent=agent)
            popen_args: Any = bwrap_cmd if bwrap_cmd else cmd
            use_shell = not bool(bwrap_cmd)

            if not bwrap_cmd and on_output:
                try:
                    on_output("[SANDBOX NOTICE] Bubblewrap (bwrap) not installed — running unconfined on host.")
                except Exception:
                    pass

            output_lines: List[str] = []
            last_progress_msg: Optional[str] = None
            proc = subprocess.Popen(
                popen_args,
                shell=use_shell,
                cwd=str(workspace_root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=clean_env,
                start_new_session=True,
            )

            def _read_stdout() -> None:
                nonlocal last_progress_msg
                if not proc.stdout:
                    return
                try:
                    for raw_line in iter(proc.stdout.readline, ""):
                        stripped = raw_line.strip()
                        if stripped.startswith("[SAFI_PROGRESS]"):
                            prog = stripped[len("[SAFI_PROGRESS]") :].strip()
                            if prog:
                                last_progress_msg = prog
                                if on_output:
                                    try:
                                        on_output(prog)
                                    except Exception as exc:
                                        logger.debug("Progress callback error: %s", exc)
                            continue
                        output_lines.append(raw_line)
                        if stripped and on_output:
                            try:
                                on_output(stripped)
                            except Exception as exc:
                                logger.debug("Output callback error: %s", exc)
                except Exception as exc:
                    logger.warning("bash stdout reader thread aborted: %s", exc)

            reader_thread = threading.Thread(target=_read_stdout, daemon=True)
            reader_thread.start()

            try:
                returncode = proc.wait(timeout=bash_timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except Exception as exc:
                    logger.debug("killpg SIGTERM failed for pid %s: %s", proc.pid, exc)
                    try:
                        proc.terminate()
                    except Exception as exc2:
                        logger.debug("terminate failed for pid %s: %s", proc.pid, exc2)
                try:
                    proc.wait(timeout=2)
                except Exception as exc:
                    logger.debug("bash process %s did not exit after SIGTERM: %s", proc.pid, exc)
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except Exception as exc2:
                        logger.debug("killpg SIGKILL failed for pid %s: %s", proc.pid, exc2)
                        try:
                            proc.kill()
                        except Exception as exc3:
                            logger.warning("Could not kill timed-out bash process %s: %s", proc.pid, exc3)
                reader_thread.join(timeout=1.0)
                partial_out = "".join(output_lines).strip()
                if len(partial_out) > 4000:
                    partial_out = "... [earlier output truncated]\n" + partial_out[-4000:]
                msg_parts = [f"Error: 'bash' timed out after {bash_timeout}s."]
                if last_progress_msg:
                    msg_parts.append(f"Last reported progress: {last_progress_msg}")
                if partial_out:
                    msg_parts.append(f"Partial output captured before timeout:\n{partial_out}")
                cmd_lower = cmd.lower()
                is_remote_or_service = is_sysadmin or any(
                    tok in cmd_lower
                    for tok in (
                        "sys-exec",
                        "ssh ",
                        "install-windowsfeature",
                        "install-adds",
                        "restart-computer",
                        "reboot",
                        "apt ",
                        "apt-get",
                        "dnf ",
                        "yum ",
                        "systemctl",
                    )
                )
                if is_remote_or_service:
                    msg_parts.append(
                        "IMPORTANT: Remote installations, domain promotions, or reboots may still be "
                        "completing in the background on the target host. Before re-running this command, "
                        "inspect the current remote state (e.g. Get-WindowsFeature, Get-Service, "
                        "Get-Process TiWorker, ps aux, or uptime) to check if the operation already "
                        "succeeded or is still running."
                    )
                else:
                    msg_parts.append("Narrow the command or run it in smaller steps.")
                return "\n".join(msg_parts)

            reader_thread.join(timeout=1.0)
            out = "".join(output_lines)
            if len(out) > 20000:
                out = out[:20000] + f"\n... [output truncated, {len(out)} chars total]"
            return f"Exit code {returncode}\n{out}".strip()

        elif name in ("task", "delegate_subagent"):
            desc = args.get("description", "")
            return f"Subagent task '{desc}' processed."

        elif name in ("question", "ask_user"):
            q_text = args.get("question") or ""
            return f"Clarification requested: {q_text}"

        elif name == "git_status":
            proc = subprocess.run(
                ["git", "status", "--short", "--branch"],
                cwd=str(workspace_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
            )
            out = proc.stdout.strip() if proc.stdout else "(clean working tree)"
            return f"Git Status:\n{out}"

        elif name == "git_diff":
            staged = bool(args.get("staged", False))
            path_arg = (args.get("path") or "").strip()
            diff_cmd = ["git", "diff"]
            if staged:
                diff_cmd.append("--staged")
            if path_arg:
                resolve_safe_path(path_arg, workspace_root)
                diff_cmd.extend(["--", path_arg])
            proc = subprocess.run(
                diff_cmd,
                cwd=str(workspace_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=60,
            )
            out = proc.stdout.strip() if proc.stdout else "(no diff)"
            if len(out) > 20000:
                out = out[:20000] + f"\n... [diff truncated, {len(out)} chars total]"
            return out

        elif name == "m365_admin":
            from . import cloud
            action = str(args.get("action") or "").strip()
            params = args.get("params") or {}
            # Flatten top-level parameters if provided directly
            for k in ("user_id", "upn", "email", "temp_password", "force_change", "sku_id", "query", "search", "limit"):
                if k in args and k not in params:
                    params[k] = args[k]
            tenant = args.get("tenant")
            return cloud.execute_m365_admin(action=action, params=params, tenant_alias=tenant)

        elif name == "azure_admin":
            from . import cloud
            action = str(args.get("action") or "").strip()
            params = args.get("params") or {}
            # Flatten top-level parameters if provided directly
            for k in ("resource_group", "vm_name", "name", "action", "resource_type"):
                if k in args and k not in params:
                    params[k] = args[k]
            subscription = args.get("subscription")
            return cloud.execute_azure_admin(action=action, params=params, subscription_alias=subscription)

        elif name == "cloud_status":
            from . import cloud
            return cloud.execute_cloud_status()

        else:
            return f"Unknown tool: '{name}'"

    except subprocess.TimeoutExpired as exc:
        return f"Error: '{name}' timed out after {exc.timeout:.0f}s. Narrow the command or run it in smaller steps."
    except PermissionError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Tool execution error: {exc}"
