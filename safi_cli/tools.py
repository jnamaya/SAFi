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
                    "offset": {"type": "integer", "description": "1-indexed starting line number (default 1). Alias: line_start."},
                    "limit": {"type": "integer", "description": "Maximum number of lines to read (default 250)."},
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
            "description": "Delegate a unit of work to an autonomous subagent in an isolated context. Use proactively whenever a task involves multi-file exploration/search ('researcher'), running test suites ('tester'), or reviewing code changes ('code_reviewer'). Returns synthesized findings without consuming main context tokens.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Short 3-5 word summary of the delegated task."},
                    "prompt": {"type": "string", "description": "Detailed goal and instructions for the subagent."},
                    "subagent_type": {
                        "type": "string",
                        "description": "Role/persona for the subagent: 'researcher' (read-only search), 'tester' (test runner), or 'code_reviewer'.",
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
            "description": "Ask the user a clarifying question with optional multiple-choice options when requirements or architectural choices are ambiguous. Pauses the turn and returns the user's selected choice or written answer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question to ask the user."},
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
            "name": "todowrite",
            "description": "Maintain and track a plan and task checklist in the right sidebar. ONLY call this tool when necessary for complex, multi-step tasks requiring multiple phases or file modifications. Do NOT call this tool for simple single-step queries, searches, lookups, or direct answers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "Unique short identifier (e.g. '1', 'step-1')."},
                                "task": {"type": "string", "description": "Short description of the task item."},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed", "failed"],
                                    "description": "Current status of the todo item."
                                }
                            },
                            "required": ["task", "status"]
                        },
                        "description": "The updated list of todo items."
                    }
                },
                "required": ["todos"]
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


def _is_secret_name(name: str) -> bool:
    """True for credential files: exact names, key suffixes, and .env.* variants (templates excepted)."""
    lower = name.lower()
    if name in FORBIDDEN_NAMES or any(lower.endswith(s) for s in FORBIDDEN_SUFFIXES):
        return True
    if lower.startswith(".env.") and not lower.endswith(ENV_TEMPLATE_SUFFIXES):
        return True
    return False


def resolve_safe_path(rel_path: str, workspace_root: Path) -> Path:
    target = (workspace_root / rel_path).resolve()
    try:
        target.relative_to(workspace_root.resolve())
    except ValueError:
        raise PermissionError(f"Access denied: '{rel_path}' resolves outside the repository root.")

    # Secrets check
    if _is_secret_name(target.name):
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
            path_str = args.get("path") or args.get("filePath") or args.get("file_path") or ""
            if not path_str.strip():
                return "Error: 'path' parameter is required for read."
            target = resolve_safe_path(path_str, workspace_root)
            if not target.exists():
                return f"Error: No such file: {path_str}"
            if target.is_dir():
                return f"Error: {path_str} is a directory. Use list instead."

            # Robust parameter normalization for line slicing:
            # Supports offset/limit, line_start/line_end, start_line/end_line
            raw_start = args.get("offset") or args.get("line_start") or args.get("start_line") or args.get("startLine")
            raw_end = args.get("line_end") or args.get("end_line") or args.get("endLine")
            raw_limit = args.get("limit")

            offset = max(1, int(raw_start or 1))
            if raw_end is not None:
                calc_limit = max(1, int(raw_end) - offset + 1)
                limit = min(calc_limit, 2000)
            elif raw_limit is not None:
                limit = max(1, min(int(raw_limit), 2000))
            else:
                limit = 250

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
            path_str = args.get("path") or args.get("filePath") or args.get("file_path") or ""
            if not path_str.strip():
                return "Error: 'path' parameter is required for write."
            content = args.get("content") or ""
            target = resolve_safe_path(path_str, workspace_root)
            if target == workspace_root or target.is_dir():
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
                # Try CRLF/LF normalization if exact match failed
                normalized_text = text.replace("\r\n", "\n")
                normalized_target = target_str.replace("\r\n", "\n")
                normalized_replacement = replacement_str.replace("\r\n", "\n")
                if normalized_target in normalized_text and normalized_text.count(normalized_target) == 1:
                    new_text = normalized_text.replace(normalized_target, normalized_replacement, 1)
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
            target = resolve_safe_path(path_str, workspace_root)
            if not target.exists():
                return f"Error: No such file or directory: {path_str}"
            if target == workspace_root:
                return "Error: Cannot delete the repository root directory."
            if target.is_file() or target.is_symlink():
                target.unlink()
                return f"Successfully deleted file: {path_str}"
            elif target.is_dir():
                import shutil
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

            # Fast path: use git grep if inside git repository
            if (workspace_root / ".git").is_dir():
                try:
                    # -e keeps a pattern like "-v" from being parsed as a git option.
                    cmd = ["git", "grep", "-n", "-I", "-E", "-e", pattern, "--"]
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

        elif name in ("task", "delegate_subagent"):
            desc = args.get("description", "")
            return f"Subagent task '{desc}' processed."

        elif name in ("question", "ask_user"):
            q_text = args.get("question") or ""
            return f"Clarification requested: {q_text}"

        elif name in ("todowrite", "todo_write"):
            todos = args.get("todos") or []
            return f"Updated plan with {len(todos)} task(s)."

        elif name == "git_status":
            proc = subprocess.run(
                "git status --short --branch",
                shell=True,
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
                # Confine and validate the path; never hand model input to a shell.
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

        else:
            return f"Unknown tool: '{name}'"

    except subprocess.TimeoutExpired as exc:
        return f"Error: '{name}' timed out after {exc.timeout:.0f}s. Narrow the command or run it in smaller steps."
    except PermissionError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        return f"Tool execution error: {exc}"
