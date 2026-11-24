import asyncio
import fnmatch
import io
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("coding_tools_mcp")

_SKIP_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", ".tox", ".eggs",
    "vector_store", ".cache", "cache",
})

_MAX_FILE_BYTES = 512 * 1024
_DEFAULT_READ_LIMIT = 2000
_MAX_READ_LINES = 5000
_MAX_RESULTS = 200
_MAX_PATTERN_CHARS = 500

_TEXT_SNIFF_BYTES = 8192

_FORBIDDEN_FILE_SUFFIXES = (
    ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore",
    ".env", ".envrc", ".netrc", ".pgpass", ".htpasswd",
)


def _root() -> Path:
    configured = os.environ.get("SAFI_CODE_REVIEW_ROOT", "/app").strip()
    return Path(configured).expanduser()


def _resolve_within_root(candidate: str, root: Optional[Path] = None) -> Path:
    base = (root or _root()).resolve()
    if not candidate or not isinstance(candidate, str):
        raise ValueError("A path is required.")
    raw = Path(candidate).expanduser()
    target = (raw if raw.is_absolute() else base / raw).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError(
            f"Path '{candidate}' resolves outside the permitted root ({base}). "
            "Only files under the configured workspace root are readable."
        )
    return target


def _is_binary_buffer(block: bytes) -> bool:
    if not block:
        return False
    if b"\x00" in block:
        return True
    printable = sum(
        1 for b in block if b in (9, 10, 13) or 32 <= b <= 126 or b >= 128
    )
    return printable / len(block) < 0.75


def _looks_binary(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            block = fh.read(_TEXT_SNIFF_BYTES)
    except OSError:
        return False
    return _is_binary_buffer(block)


def _is_hidden_or_skipped(path: Path, root: Path) -> bool:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return True
    for part in rel.parts[:-1]:
        if part in _SKIP_DIRS or part.startswith("."):
            return True
    return False


def _is_forbidden_file(path: Path, root: Path) -> bool:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return True
    name = rel.name
    if name.startswith("."):
        return True
    lowered = name.lower()
    return any(
        lowered.endswith(suffix) for suffix in _FORBIDDEN_FILE_SUFFIXES
    )


def _glob_variants(pattern: str) -> List[str]:
    variants = [pattern]
    if "**/" in pattern:
        variants.append(pattern.replace("**/", "*"))
    return variants


def _walk(root: Path, pattern: str, limit: int) -> List[str]:
    results: List[str] = []
    variants = _glob_variants(pattern)
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        dirnames[:] = [
            d for d in sorted(dirnames)
            if d not in _SKIP_DIRS and not d.startswith(".")
        ]
        for filename in sorted(filenames):
            if filename.startswith("."):
                continue
            candidate = current / filename
            if _is_hidden_or_skipped(candidate, root):
                continue
            rel = candidate.relative_to(root).as_posix()
            if any(
                fnmatch.fnmatch(rel, v) or fnmatch.fnmatch(filename, v)
                for v in variants
            ):
                results.append(rel)
                if len(results) >= limit:
                    return results
    return results


def _grep_files(
    root: Path, pattern: str, glob_filter: Optional[str], limit: int
) -> List[Dict[str, Any]]:
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"Invalid regular expression: {exc}")

    glob_regexes = (
        [re.compile(fnmatch.translate(v)) for v in _glob_variants(glob_filter)]
        if glob_filter
        else None
    )

    matches: List[Dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        dirnames[:] = [
            d for d in sorted(dirnames)
            if d not in _SKIP_DIRS and not d.startswith(".")
        ]
        for filename in sorted(filenames):
            if filename.startswith("."):
                continue
            path = current / filename
            rel = path.relative_to(root).as_posix()
            if glob_regexes and not any(
                r.match(rel) or r.match(filename) for r in glob_regexes
            ):
                continue
            if _is_hidden_or_skipped(path, root):
                continue
            if _is_forbidden_file(path, root):
                continue
            try:
                if path.stat().st_size > _MAX_FILE_BYTES:
                    continue
                with path.open("rb") as raw_fh:
                    sniff = raw_fh.read(_TEXT_SNIFF_BYTES)
                    if _is_binary_buffer(sniff):
                        continue
                    raw_fh.seek(0)
                    with io.TextIOWrapper(raw_fh, encoding="utf-8", errors="replace") as text_fh:
                        for lineno, line in enumerate(text_fh, start=1):
                            if regex.search(line):
                                matches.append({
                                    "file": rel,
                                    "line": lineno,
                                    "text": line.strip()[:300],
                                })
                                if len(matches) >= limit:
                                    return matches
            except OSError as exc:
                logger.debug("grep skipped %s: %s", rel, exc)
                continue
    return matches


async def read_file(path: str, offset: int = 1, limit: int = _DEFAULT_READ_LIMIT) -> str:
    def _work() -> str:
        try:
            target = _resolve_within_root(path)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

        if not target.exists():
            return json.dumps({"error": f"No such file: {path}"})
        if target.is_dir():
            return json.dumps({
                "error": f"{path} is a directory. Use the list tool to enumerate it."
            })
        if _is_hidden_or_skipped(target, _root().resolve()) or _is_forbidden_file(
            target, _root().resolve()
        ):
            return json.dumps({
                "error": (
                    f"{path} is a hidden or credential-bearing file and was not "
                    "read. Point at source under the workspace instead."
                ),
            })

        try:
            size = target.stat().st_size
        except OSError as exc:
            return json.dumps({"error": f"Cannot stat {path}: {exc}"})

        if size > _MAX_FILE_BYTES:
            return json.dumps({
                "error": (
                    f"{path} is {size} bytes, above the {_MAX_FILE_BYTES}-byte "
                    "read limit. Use grep to locate the relevant lines."
                ),
            })
        start = max(1, int(offset or 1))
        max_requested = max(1, min(int(limit or _DEFAULT_READ_LIMIT), _MAX_READ_LINES))
        end = start + max_requested

        window: List[str] = []
        total = 0
        try:
            with target.open("rb") as raw_fh:
                sniff = raw_fh.read(_TEXT_SNIFF_BYTES)
                if _is_binary_buffer(sniff):
                    return json.dumps({
                        "error": f"{path} appears to be a binary file and was not read."
                    })
                raw_fh.seek(0)
                with io.TextIOWrapper(raw_fh, encoding="utf-8", errors="replace") as text_fh:
                    for lineno, line in enumerate(text_fh, start=1):
                        total = lineno
                        if start <= lineno < end:
                            window.append(line.rstrip("\r\n"))
        except OSError as exc:
            return json.dumps({"error": f"Cannot read {path}: {exc}"})

        if start > total:
            return json.dumps({
                "error": f"offset {start} is past the end of {path} ({total} lines)."
            })
        body = "\n".join(
            f"{start + i}: {line}" for i, line in enumerate(window)
        )
        return json.dumps({
            "path": target.relative_to(_root().resolve()).as_posix()
                    if target.is_relative_to(_root().resolve()) else path,
            "offset": start,
            "lines_returned": len(window),
            "total_lines": total,
            "truncated": start - 1 + len(window) < total,
            "content": body,
        })

    return await asyncio.to_thread(_work)


async def grep(pattern: str, path: str = ".", include: Optional[str] = None,
               limit: int = 100) -> str:
    def _work() -> str:
        if not pattern or not isinstance(pattern, str):
            return json.dumps({"error": "A search pattern is required."})
        if len(pattern) > _MAX_PATTERN_CHARS:
            return json.dumps({
                "error": (
                    f"Pattern is {len(pattern)} characters, above the "
                    f"{_MAX_PATTERN_CHARS}-character limit. Narrow it."
                ),
            })

        root = _root().resolve()
        try:
            scope = _resolve_within_root(path or ".")
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

        if scope.is_file():
            search_root, rel_prefix = scope.parent, scope.name
        else:
            search_root, rel_prefix = scope, ""

        capped = max(1, min(int(limit or 100), _MAX_RESULTS))
        try:
            matches = _grep_files(search_root, pattern, include, capped)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

        if rel_prefix:
            for m in matches:
                m["file"] = f"{rel_prefix}/{m['file']}"

        return json.dumps({
            "pattern": pattern,
            "match_count": len(matches),
            "truncated": len(matches) >= capped,
            "matches": matches,
        })

    return await asyncio.to_thread(_work)


async def glob_files(pattern: str, path: str = ".") -> str:
    def _work() -> str:
        if not pattern or not isinstance(pattern, str):
            return json.dumps({"error": "A glob pattern is required."})

        root = _root().resolve()
        try:
            scope = _resolve_within_root(path or ".")
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

        if scope.is_file():
            return json.dumps({
                "files": [scope.relative_to(root).as_posix()], "truncated": False
            })

        found = _walk(scope, pattern, _MAX_RESULTS)
        rel_base = scope.relative_to(root).as_posix() if scope != root else ""
        files = [f"{rel_base}/{f}" if rel_base else f for f in found]
        return json.dumps({
            "pattern": pattern,
            "file_count": len(files),
            "truncated": len(files) >= _MAX_RESULTS,
            "files": files,
        })

    return await asyncio.to_thread(_work)


async def list_directory(path: str = ".", limit: int = _MAX_RESULTS) -> str:
    def _work() -> str:
        try:
            target = _resolve_within_root(path or ".")
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

        if not target.exists():
            return json.dumps({"error": f"No such directory: {path}"})
        if not target.is_dir():
            return json.dumps({
                "error": f"{path} is a file. Use the read tool to see its contents."
            })

        try:
            entries = sorted(
                target.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except OSError as exc:
            return json.dumps({"error": f"Cannot list {path}: {exc}"})

        capped = max(1, min(int(limit or _MAX_RESULTS), _MAX_RESULTS))
        visible: List[Dict[str, Any]] = []
        for entry in entries:
            name = entry.name
            if name.startswith(".") or name in _SKIP_DIRS:
                continue
            try:
                is_dir = entry.is_dir()
                size = None if is_dir else entry.stat().st_size
            except OSError:
                continue
            visible.append({"name": name, "type": "dir" if is_dir else "file",
                            "size": size})

        return json.dumps({
            "path": target.relative_to(_root().resolve()).as_posix()
                    if target.is_relative_to(_root().resolve()) else path,
            "entry_count": len(visible),
            "truncated": len(visible) > capped,
            "entries": visible[:capped],
        })

    return await asyncio.to_thread(_work)


CODING_HARNESS_TOOL_NAMES: Tuple[str, ...] = (
    "read", "grep", "glob", "list",
    "bash", "write", "edit", "patch", "delete",
    "webfetch", "websearch", "task", "todowrite", "skill", "lsp", "question",
)
OPENCODE_TOOL_NAMES: Tuple[str, ...] = CODING_HARNESS_TOOL_NAMES

SAFI_EXECUTED_TOOLS = frozenset({"read", "grep", "glob", "list"})

BUILTIN_TOOL_FUNCTIONS: Tuple[str, ...] = CODING_HARNESS_TOOL_NAMES
