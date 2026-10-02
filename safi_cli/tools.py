"""Local repository tools and execution engine for SAFi CLI.

These tools execute directly on the developer's local filesystem in the
current working directory, under SAFi's Will Gate and path confinement.
"""

import fnmatch
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

FORBIDDEN_NAMES = frozenset({".env", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"})
FORBIDDEN_SUFFIXES = (
    ".pem", ".key", ".pkcs12", ".pfx", ".p12", ".kdbx", ".jks",
)
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


TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "Read file contents with 1-indexed line numbers. Path is relative to the repository root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to repository root."},
                    "offset": {"type": "integer", "description": "1-indexed starting line number (default 1)."},
                    "limit": {"type": "integer", "description": "Maximum number of lines to read (default 250)."}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write",
            "description": "Create or overwrite a file with full content. Path is relative to the repository root.",
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
            "description": "Replace an exact target text sequence in a file with replacement content.",
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
    }
]


def resolve_safe_path(rel_path: str, workspace_root: Path) -> Path:
    target = (workspace_root / rel_path).resolve()
    try:
        target.relative_to(workspace_root.resolve())
    except ValueError:
        raise PermissionError(f"Access denied: '{rel_path}' resolves outside the repository root.")

    # Secrets check
    if target.name in FORBIDDEN_NAMES or any(target.name.lower().endswith(s) for s in FORBIDDEN_SUFFIXES):
        raise PermissionError(f"Access denied: '{target.name}' is a secret/credential file and cannot be accessed.")
    return target


def execute_tool(
    name: str,
    args: Dict[str, Any],
    workspace_root: Path,
) -> str:
    """Execute a tool proposal locally inside workspace_root."""
    try:
        if name == "read":
            path_str = args.get("path") or ""
            target = resolve_safe_path(path_str, workspace_root)
            if not target.exists():
                return f"Error: No such file: {path_str}"
            if target.is_dir():
                return f"Error: {path_str} is a directory. Use list instead."

            offset = max(1, int(args.get("offset") or 1))
            limit = max(1, min(int(args.get("limit") or 250), 2000))

            with target.open("r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()

            total = len(lines)
            if offset > total:
                return f"Error: offset {offset} is past end of file ({total} lines total)."

            slice_lines = lines[offset - 1 : offset - 1 + limit]
            body = "".join(f"{offset + i}: {line}" for i, line in enumerate(slice_lines))
            truncated = (offset - 1 + len(slice_lines)) < total
            note = f"\n... [truncated, {total} lines total]" if truncated else ""
            return body + note

        elif name == "write":
            path_str = args.get("path") or ""
            content = args.get("content") or ""
            target = resolve_safe_path(path_str, workspace_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} characters to {path_str}."

        elif name == "edit":
            path_str = args.get("path") or ""
            target_str = args.get("target") or ""
            replacement_str = args.get("replacement") or ""
            target = resolve_safe_path(path_str, workspace_root)
            if not target.exists():
                return f"Error: No such file: {path_str}"

            text = target.read_text(encoding="utf-8", errors="replace")
            count = text.count(target_str)
            if count == 0:
                return f"Error: Target text block not found in {path_str}. Verify whitespace and indentation."
            if count > 1:
                return f"Error: Target text occurs {count} times in {path_str}. Provide more surrounding lines for uniqueness."

            new_text = text.replace(target_str, replacement_str, 1)
            target.write_text(new_text, encoding="utf-8")
            return f"Successfully applied edit to {path_str}."

        elif name == "grep":
            pattern = args.get("pattern") or ""
            sub_path = args.get("path") or "."
            include = args.get("include")
            search_dir = resolve_safe_path(sub_path, workspace_root)
            if not search_dir.exists():
                return f"Error: Path does not exist: {sub_path}"

            max_matches = 100

            # Fast path: use git grep if inside git repository
            if (workspace_root / ".git").is_dir():
                try:
                    cmd = ["git", "grep", "-n", "-I", "-E", pattern]
                    if include:
                        cmd.extend(["--", f"*{include}*"])
                    elif sub_path != ".":
                        cmd.extend(["--", sub_path])
                    proc = subprocess.run(
                        cmd,
                        cwd=str(workspace_root),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=5,
                    )
                    if proc.returncode == 0:
                        lines = [l for l in proc.stdout.splitlines() if l.strip()]
                        if len(lines) > max_matches:
                            return "\n".join(lines[:max_matches]) + f"\n... [reached {max_matches} match limit]"
                        return "\n".join(lines)
                    elif proc.returncode == 1:
                        return f"No matches found for pattern: '{pattern}'"
                except Exception:
                    pass

            try:
                regex = re.compile(pattern, re.IGNORECASE)
            except re.error:
                regex = None
            matches: List[str] = []

            for dirpath, dirnames, filenames in os.walk(search_dir):
                dirnames[:] = [d for d in sorted(dirnames) if d not in SKIP_DIRS and not d.startswith(".")]
                for f in sorted(filenames):
                    if f.startswith(".") or f in FORBIDDEN_NAMES or any(f.endswith(s) for s in FORBIDDEN_SUFFIXES):
                        continue
                    if any(f.lower().endswith(ext) for ext in BINARY_EXTENSIONS):
                        continue
                    if include and not fnmatch.fnmatch(f, include):
                        continue
                    file_path = Path(dirpath) / f
                    try:
                        if file_path.stat().st_size > MAX_GREP_FILE_SIZE:
                            continue
                        rel = file_path.relative_to(workspace_root).as_posix()
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
                dirnames[:] = [d for d in sorted(dirnames) if d not in SKIP_DIRS and not d.startswith(".")]
                for f in sorted(filenames):
                    if f.startswith("."):
                        continue
                    if any(f.lower().endswith(ext) for ext in BINARY_EXTENSIONS):
                        continue
                    file_path = Path(dirpath) / f
                    try:
                        rel = file_path.relative_to(workspace_root).as_posix()
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
                if item.name.startswith(".") or item.name in SKIP_DIRS:
                    continue
                suffix = "/" if item.is_dir() else ""
                entries.append(f"{item.name}{suffix}")
            return "\n".join(entries) if entries else "(empty directory)"

        elif name == "bash":
            cmd = args.get("command") or ""
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=str(workspace_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=120,
            )
            out = proc.stdout or ""
            if len(out) > 20000:
                out = out[:20000] + f"\n... [output truncated, {len(out)} chars total]"
            return f"Exit code {proc.returncode}\n{out}".strip()

        else:
            return f"Unknown tool: '{name}'"

    except Exception as exc:
        return f"Tool execution error: {exc}"
