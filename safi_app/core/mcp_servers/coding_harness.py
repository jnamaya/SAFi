"""Coding-harness MCP server — tool vocabulary for coding-agent clients.

WHY THIS EXISTS
---------------
Coding clients propose tools by bare name ("task", "bash", "edit"). WillGate
matches those names EXACTLY against profile["allowed_tools"], so any name no
connector declares can never be authorized and the agent collects a violation
on every turn it tries to work.

So this connector declares the coding harness tool vocabulary, which makes those
names resolvable, describable and grantable. A declaration is NOT an
implementation — see EXECUTION below.

EXECUTION: WHO RUNS WHAT
------------------------
The read-only repository tools (read, grep, glob, list) are implemented here and
run inside SAFi. The rest are declared but NOT executed by SAFi:

  * The client (e.g. safi-cli) owns execution for the tools it advertises. It runs
    `bash`, `write` and `edit` on the HOST, under client permission prompts, and
    reports results back as tool messages.
  * task, todowrite, skill, lsp, question and webfetch/websearch are client-side
    primitives or extended harness orchestration tools.

execute_tool() returns an explicit error for these rather than pretending.
The alternative — a shell or file-write executor inside the SAFi container — is
remote code execution on the app container, and it belongs behind its own
deliberate decision, not as a side effect of matching a tool list.

Note the consequence, because it matters for how the policy is written: because
the policy grants the CONNECTOR name, widening this tuple widens every policy
that names `coding_harness`. That is why the policy in this deployment lists
functions explicitly instead (see the narrow-within-a-connector behaviour the
tool_connectors tests cover), so a future addition here cannot silently enlarge
an existing grant.

WHY THE PATH CONFINEMENT IS NOT OPTIONAL
----------------------------------------
A built-in connector runs in-process inside the SAFi container. Without a root,
`read("/app/.env")` would hand the model the database password and the policy
API key, and `glob("**/*")` would enumerate the deployment to find them. The
retriever draws the same line for knowledge bases (see
services/retriever.py): a path is resolved, then checked to be inside an
allow-listed root, and the check is on the RESOLVED path so a symlink or a ".."
cannot step outside it.

The root is SAFI_CODE_REVIEW_ROOT (default /app, the image's application tree).
Operators reviewing a different checkout set it to that directory and mount it
in; nothing here assumes the tree is the repo this file ships in.
"""
import asyncio
import fnmatch
import io
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("coding_harness_mcp")

# Directories that are never worth offering to a reviewer and are where
# credentials, caches and dependency trees live. Skipped during traversal so a
# recursive glob cannot walk a multi-gigabyte tree to answer a one-line question.
_SKIP_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", ".tox", ".eggs",
    "vector_store", ".cache", "cache",
})

# A file big enough to blow past the model's context in one tool result is a
# denial of service against the turn, not a useful read.
_MAX_FILE_BYTES = 512 * 1024
# Matches opencode's read defaults so the agent's mental model of offsets holds.
_DEFAULT_READ_LIMIT = 2000
_MAX_READ_LINES = 5000
# Bound every listing so a broad pattern cannot produce an unbounded payload.
_MAX_RESULTS = 200
# Guard the regex engine: a pathological pattern must not stall the event loop.
_MAX_PATTERN_CHARS = 500

# Refuse anything that looks binary rather than emitting mojibake the model
# would then try to reason about. NUL in the first block is the usual signal;
# the high-ratio check catches UTF-16 and packed binaries that lack it.
_TEXT_SNIFF_BYTES = 8192

# Credential-bearing files that are not conventionally dotfiles, so a
# dotfile check alone would leave them readable through `read`.
_FORBIDDEN_FILE_SUFFIXES = (
    ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore",
    ".env", ".envrc", ".netrc", ".pgpass", ".htpasswd",
)


def _root() -> Path:
    configured = os.environ.get("SAFI_CODE_REVIEW_ROOT", "/app").strip()
    return Path(configured).expanduser()


def _resolve_within_root(candidate: str, root: Optional[Path] = None) -> Path:
    """Resolve `candidate` and refuse anything that lands outside the root.

    Returns the resolved path. Raises ValueError with a model-readable message
    on refusal, because the model asked for the path and deserves to be told
    why it did not get one — silently returning nothing would read as "no such
    file" and send it hunting elsewhere.

    The containment test compares RESOLVED paths (symlinks followed), so a link
    inside the root pointing out of it is refused, and so is "..". Both root and
    candidate are absolutized first, or a relative path would resolve against
    the process CWD and compare unequal for reasons that have nothing to do with
    security.
    """
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
    """True when any DIRECTORY component under the root is a skip-dir or dotdir.

    Checked per component rather than on the basename so "src/.venv/x" is
    excluded too. Hidden directories are skipped because .git and .venv are
    exactly what a reviewer must not walk.

    The basename is deliberately not examined here: this predicate guards
    traversal, where the final file is a candidate the caller has already
    decided about. `_is_forbidden_file` is the separate check for the case
    where the final file is itself the target.
    """
    try:
        rel = path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return True
    for part in rel.parts[:-1]:
        if part in _SKIP_DIRS or part.startswith("."):
            return True
    return False


def _is_forbidden_file(path: Path, root: Path) -> bool:
    """True when the target itself may not be read: a dotfile, or inside one.

    Distinct from _is_hidden_or_skipped because `read` names the final file
    directly, and the file it names most often is one that must stay secret.
    `.env` in this very repository holds DB_PASSWORD and SAFI_POLICY_API_KEY,
    so a traversal-confined read that still honoured `.env` would hand the
    model the deployment's credentials while appearing correctly jailed.

    Private keys and credential extensions are refused by name as well, since
    they are not conventionally dotfiles and would otherwise pass.
    """
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
    """Match forms for a glob pattern.

    fnmatch's `*` already crosses "/", so the literal separator in a `**/`
    segment is the only thing preventing the common recursive pattern from
    working: `**/*.py` cannot match "coding_harness.py", a file sitting directly
    in the searched directory. In shell terms `**/` means *zero or more*
    directories, so collapsing it to `*` restores that. Both forms are tried
    and neither widens the pattern beyond what its tail already allowed.
    """
    variants = [pattern]
    if "**/" in pattern:
        variants.append(pattern.replace("**/", "*"))
    return variants


def _walk(root: Path, pattern: str, limit: int) -> List[str]:
    """Files under `root` whose relative path matches a glob `pattern`.

    Matching is done on the POSIX-style relative path so one pattern works the
    same way it would in a shell. os.walk is pruned in place at the skip-dirs,
    which is what keeps `**/*.py` from descending into node_modules.

    Note `root` here is the SEARCH SCOPE, so a relative path is relative to
    that scope and not to the workspace root; glob_files re-attaches the scope
    prefix to the results afterwards. That is why the pattern is matched
    against both the scoped relative path and the bare filename.
    """
    results: List[str] = []
    variants = _glob_variants(pattern)
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        # Prune before descending, so skipped trees are never entered at all.
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
    """Regex search over text files, newest-first match order per file.

    The compiled pattern is built once and length-capped: re.search on a
    pathological alternation is CPU-bound and this runs on the event loop
    (via to_thread, so the loop itself is protected).
    """
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
            # grep must honour the same file-level refusal as read: otherwise a
            # pattern like "SECRET|PASSWORD" extracts the contents of a file the
            # read tool would have declined to open.
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


# ---------------------------------------------------------------------------
# Tool functions. Each returns a JSON string, never raises: an exception here
# surfaces to the model as a broken tool call rather than as readable output,
# and the established convention in this package is to return an error payload.
# ---------------------------------------------------------------------------


async def read_file(path: str, offset: int = 1, limit: int = _DEFAULT_READ_LIMIT) -> str:
    """Read a UTF-8 text file from the workspace, 1-indexed by line.

    `offset` is 1-indexed and `limit` counts lines, matching opencode's read so
    a model that has seen one paginates correctly in the other. Output carries
    line numbers in the form "N: text" because a model reasoning about code
    needs to cite the line it is talking about, and re-counting a raw blob to
    find it is where off-by-one errors come from.

    Refuses binaries, files above the size cap, and any path resolving outside
    the workspace root. Those refusals are returned as error payloads so the
    model can adapt (read a different file, or ask for a narrower slice).
    """
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

        # Clamp rather than error: asking past the end is an off-by-one, and
        # answering with the tail is more useful than refusing.
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
    """Regex-search file contents and return file/line/text for each match.

    `include` is a glob filter (e.g. "*.py"); omitting it searches every text
    file under the root. Results are capped so a pattern matching everything
    returns a bounded payload rather than the repository.
    """
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
    """Find files by glob pattern, returning workspace-relative paths.

    Patterns are matched against the relative path and the bare filename, so
    both "**/*.py" and "*.py" find Python files. Results are sorted and capped;
    a pattern matching the whole tree reports truncation rather than silently
    returning an arbitrary prefix.
    """
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

        # Guard the traversal itself: a bare "**" matches every file in the tree,
        # and os.walk over the whole application directory is slow enough to be
        # felt. Stopping at the cap bounds the work.
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
    """List the entries of one directory, directories first.

    A single directory rather than a recursive walk: it is the tool that answers
    "what is in here", and recursion is what glob is for. Sorted with
    directories ahead of files so the shape of a tree is legible without
    parsing the output.
    """
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


# The connector's full vocabulary: coding harness model-facing tool set.
# Declaring a name is what makes it resolvable by the catalog and grantable by a
# policy; it is not a claim that SAFi implements it (see EXECUTION in the module
# docstring). SAFI_EXECUTED_TOOLS marks the ones SAFi runs; the rest are
# executed by the client (e.g. safi-cli). Order matches get_tools_for_agent's
# emission order, which test_tool_connector_expansion asserts.
CODING_HARNESS_TOOL_NAMES: Tuple[str, ...] = (
    "read", "grep", "glob", "list",
    "bash", "write", "edit", "patch",
    "webfetch", "websearch", "task", "todowrite", "skill", "lsp", "question",
)
OPENCODE_TOOL_NAMES: Tuple[str, ...] = CODING_HARNESS_TOOL_NAMES

# Declared and SAFi-executed. Everything else in the vocabulary is a
# client-side primitive; execute_tool returns an explicit refusal for those.
SAFI_EXECUTED_TOOLS = frozenset({"read", "grep", "glob", "list"})

BUILTIN_TOOL_FUNCTIONS: Tuple[str, ...] = CODING_HARNESS_TOOL_NAMES
