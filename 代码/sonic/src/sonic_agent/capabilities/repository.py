"""Bounded, read-only repository capabilities.

The trusted application binds these tools to one repository root. Tool calls only
receive relative POSIX paths and can neither replace nor widen that root.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any, Iterator

from .tools import ToolError, ToolOutput, ToolRegistry, ToolSpec


_TRUST_LABEL = "untrusted_repository_content"
_SENSITIVE_NAMES = {
    ".git",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
}
_SENSITIVE_SUFFIXES = {".key", ".p12", ".pem", ".pfx"}
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}
_IGNORED_DIRECTORIES = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
    "vendor",
}


@dataclass(frozen=True)
class WorkspaceLimits:
    """Hard resource bounds for repository inspection."""

    max_path_chars: int = 1024
    max_file_bytes: int = 1_048_576
    max_read_lines: int = 400
    max_line_chars: int = 8_192
    max_output_chars: int = 65_536
    max_list_depth: int = 3
    max_list_entries: int = 500
    max_search_query_chars: int = 256
    max_search_files: int = 2_000
    max_search_bytes: int = 32 * 1_048_576
    max_search_results: int = 100
    max_preview_chars: int = 300

    def __post_init__(self) -> None:
        for value in self.__dict__.values():
            if type(value) is not int or value <= 0:
                raise ValueError("workspace limits must be positive integers")


@dataclass(frozen=True)
class _FileSnapshot:
    data: bytes
    size: int
    sha256: str


class WorkspaceScope:
    """A stable capability scoped to one trusted, existing repository root."""

    def __init__(
        self,
        root: Path,
        root_identity: tuple[int, int],
        allowed_roots: tuple[Path, ...],
        workspace_id: str,
        limits: WorkspaceLimits,
    ) -> None:
        self._root = root
        self._root_identity = root_identity
        self._allowed_roots = allowed_roots
        self.workspace_id = workspace_id
        self.limits = limits

    @classmethod
    def open(
        cls,
        root: str | os.PathLike[str],
        *,
        allowed_paths: tuple[str, ...] = (".",),
        limits: WorkspaceLimits | None = None,
    ) -> "WorkspaceScope":
        if not isinstance(root, (str, os.PathLike)):
            raise TypeError("workspace root must be path-like")
        configured = Path(root)
        cls._reject_link_or_special(configured, expect_directory=True)
        try:
            resolved = configured.resolve(strict=True)
            root_stat = resolved.stat()
        except OSError:
            raise ValueError("workspace root is unavailable") from None
        if not stat.S_ISDIR(root_stat.st_mode):
            raise ValueError("workspace root must be a directory")
        identity = (root_stat.st_dev, root_stat.st_ino)
        selected_limits = limits or WorkspaceLimits()
        workspace_id = "ws_" + hashlib.sha256(
            f"{resolved}|{identity[0]}|{identity[1]}".encode("utf-8")
        ).hexdigest()[:20]

        provisional = cls(resolved, identity, (), workspace_id, selected_limits)
        if not allowed_paths:
            raise ValueError("at least one allowed path is required")
        allowed: list[Path] = []
        for value in allowed_paths:
            relative = provisional._relative_path(value, allow_root=True)
            candidate = provisional._resolve(relative, expected="directory", check_scope=False)
            allowed.append(candidate)
        unique = tuple(sorted(set(allowed), key=lambda item: (len(item.parts), str(item))))
        return cls(resolved, identity, unique, workspace_id, selected_limits)

    @staticmethod
    def _reject_link_or_special(path: Path, *, expect_directory: bool = False) -> None:
        try:
            info = path.lstat()
        except OSError:
            raise ValueError("workspace root is unavailable") from None
        attributes = getattr(info, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        is_reparse = bool(attributes & reparse_flag)
        is_junction = bool(getattr(path, "is_junction", lambda: False)())
        if stat.S_ISLNK(info.st_mode) or is_reparse or is_junction:
            raise ValueError("workspace root cannot be a link or reparse point")
        if expect_directory and not stat.S_ISDIR(info.st_mode):
            raise ValueError("workspace root must be a directory")

    @staticmethod
    def _is_sensitive_component(component: str) -> bool:
        folded = component.casefold()
        return (
            folded in _SENSITIVE_NAMES
            or folded == ".env"
            or folded.startswith(".env.")
            or PurePosixPath(folded).suffix in _SENSITIVE_SUFFIXES
        )

    def _check_root(self) -> None:
        try:
            current = self._root.stat()
        except OSError:
            raise ToolError(
                "workspace_changed",
                "workspace identity changed during the run",
                retryable=True,
                denied=True,
            ) from None
        if (current.st_dev, current.st_ino) != self._root_identity:
            raise ToolError(
                "workspace_changed",
                "workspace identity changed during the run",
                retryable=True,
                denied=True,
            )

    def _relative_path(self, value: Any, *, allow_root: bool) -> PurePosixPath:
        if not isinstance(value, str):
            raise ToolError("invalid_argument", "path must be a string", denied=True)
        if not value or len(value) > self.limits.max_path_chars or "\x00" in value:
            raise ToolError("invalid_path", "path is outside the accepted form", denied=True)
        if "\\" in value or ":" in value or value.startswith("/") or value.startswith("//"):
            raise ToolError("invalid_path", "path is outside the accepted form", denied=True)
        if value == ".":
            if allow_root:
                return PurePosixPath(".")
            raise ToolError("invalid_path", "a file path is required", denied=True)
        parts = value.split("/")
        if any(
            part in {"", ".", ".."}
            or part.endswith((".", " "))
            or any(ord(character) < 32 for character in part)
            or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
            for part in parts
        ):
            raise ToolError("invalid_path", "path is outside the accepted form", denied=True)
        if any(self._is_sensitive_component(part) for part in parts):
            raise ToolError("sensitive_path", "sensitive repository paths are not readable", denied=True)
        return PurePosixPath(*parts)

    def _resolve(
        self,
        relative: PurePosixPath,
        *,
        expected: str,
        check_scope: bool = True,
    ) -> Path:
        self._check_root()
        current = self._root
        for part in relative.parts:
            if part == ".":
                continue
            current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError:
                raise ToolError("not_found", "repository path was not found") from None
            except OSError:
                raise ToolError("path_unavailable", "repository path is unavailable") from None
            attributes = getattr(info, "st_file_attributes", 0)
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            is_junction = bool(getattr(current, "is_junction", lambda: False)())
            if stat.S_ISLNK(info.st_mode) or attributes & reparse_flag or is_junction:
                raise ToolError("linked_path", "linked repository paths are not readable", denied=True)
        try:
            resolved = current.resolve(strict=True)
        except OSError:
            raise ToolError("path_unavailable", "repository path is unavailable") from None
        if not resolved.is_relative_to(self._root):
            raise ToolError("path_escape", "repository path escaped the workspace", denied=True)
        if check_scope and not any(
            resolved == allowed or resolved.is_relative_to(allowed)
            for allowed in self._allowed_roots
        ):
            raise ToolError("path_scope_denied", "repository path is outside the allowed scope", denied=True)
        try:
            mode = resolved.stat().st_mode
        except OSError:
            raise ToolError("path_unavailable", "repository path is unavailable") from None
        if expected == "file" and not stat.S_ISREG(mode):
            raise ToolError("not_a_file", "repository path is not a regular file", denied=True)
        if expected == "directory" and not stat.S_ISDIR(mode):
            raise ToolError("not_a_directory", "repository path is not a directory", denied=True)
        return resolved

    def resolve_file(self, value: Any) -> tuple[PurePosixPath, Path]:
        relative = self._relative_path(value, allow_root=False)
        return relative, self._resolve(relative, expected="file")

    def resolve_directory(self, value: Any) -> tuple[PurePosixPath, Path]:
        relative = self._relative_path(value, allow_root=True)
        return relative, self._resolve(relative, expected="directory")

    def relative_name(self, path: Path) -> str:
        return path.relative_to(self._root).as_posix() or "."

    def read_snapshot(self, path: Path) -> _FileSnapshot:
        try:
            before = path.stat()
        except OSError:
            raise ToolError("path_unavailable", "repository file is unavailable") from None
        if not stat.S_ISREG(before.st_mode):
            raise ToolError("not_a_file", "repository path is not a regular file", denied=True)
        if before.st_size > self.limits.max_file_bytes:
            raise ToolError("file_too_large", "repository file exceeds the read limit", denied=True)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
            try:
                opened = os.fstat(descriptor)
                chunks: list[bytes] = []
                remaining = self.limits.max_file_bytes + 1
                while remaining:
                    chunk = os.read(descriptor, remaining)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                data = b"".join(chunks)
                after = os.fstat(descriptor)
            finally:
                os.close(descriptor)
        except OSError:
            raise ToolError("path_unavailable", "repository file is unavailable", retryable=True) from None
        before_id = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        opened_id = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        after_id = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if before_id != opened_id or opened_id != after_id:
            raise ToolError(
                "workspace_changed",
                "repository file changed while it was being read",
                retryable=True,
                denied=True,
            )
        if len(data) > self.limits.max_file_bytes:
            raise ToolError("file_too_large", "repository file exceeds the read limit", denied=True)
        return _FileSnapshot(data, len(data), hashlib.sha256(data).hexdigest())


class ReadOnlyRepositoryTools:
    """List, read and literal-search operations bound to a WorkspaceScope."""

    def __init__(self, scope: WorkspaceScope) -> None:
        if not isinstance(scope, WorkspaceScope):
            raise TypeError("scope must be a WorkspaceScope")
        self.scope = scope

    @staticmethod
    def _arguments(arguments: dict[str, Any], allowed: set[str]) -> None:
        if not isinstance(arguments, dict):
            raise ToolError("invalid_argument", "tool arguments must be an object", denied=True)
        if set(arguments) - allowed:
            raise ToolError("invalid_argument", "tool arguments contain unsupported fields", denied=True)

    @staticmethod
    def _integer(value: Any, *, name: str, minimum: int, maximum: int) -> int:
        if type(value) is not int or not minimum <= value <= maximum:
            raise ToolError(
                "invalid_argument",
                f"{name} must be an integer between {minimum} and {maximum}",
                denied=True,
            )
        return value

    @staticmethod
    def _decode(snapshot: _FileSnapshot) -> str:
        if b"\x00" in snapshot.data:
            raise ToolError("binary_file", "binary repository files are not readable", denied=True)
        try:
            return snapshot.data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ToolError("unsupported_encoding", "repository file is not UTF-8 text", denied=True) from None

    @staticmethod
    def _entry_is_link(path: Path, info: os.stat_result) -> bool:
        attributes = getattr(info, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        return (
            stat.S_ISLNK(info.st_mode)
            or bool(attributes & reparse_flag)
            or bool(getattr(path, "is_junction", lambda: False)())
        )

    def _children(self, directory: Path) -> list[tuple[Path, os.stat_result]]:
        children: list[tuple[Path, os.stat_result]] = []
        try:
            candidates = sorted(directory.iterdir(), key=lambda item: (item.name.casefold(), item.name))
        except OSError:
            raise ToolError("path_unavailable", "repository directory is unavailable", retryable=True) from None
        for candidate in candidates:
            if WorkspaceScope._is_sensitive_component(candidate.name):
                continue
            try:
                info = candidate.lstat()
            except OSError:
                continue
            if self._entry_is_link(candidate, info):
                continue
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                continue
            children.append((candidate, info))
        return children

    def list(self, arguments: dict[str, Any]) -> ToolOutput:
        self._arguments(arguments, {"path", "depth"})
        path_value = arguments.get("path", ".")
        depth = self._integer(
            arguments.get("depth", 1),
            name="depth",
            minimum=1,
            maximum=self.scope.limits.max_list_depth,
        )
        _, directory = self.scope.resolve_directory(path_value)
        entries: list[dict[str, Any]] = []
        directories_scanned = 0
        truncated = False

        def visit(current: Path, remaining: int) -> None:
            nonlocal directories_scanned, truncated
            if truncated:
                return
            relative_current = PurePosixPath(self.scope.relative_name(current))
            current = self.scope._resolve(relative_current, expected="directory")
            directories_scanned += 1
            for child, info in self._children(current):
                if len(entries) >= self.scope.limits.max_list_entries:
                    truncated = True
                    return
                is_directory = stat.S_ISDIR(info.st_mode)
                entries.append({
                    "path": self.scope.relative_name(child),
                    "type": "directory" if is_directory else "file",
                    "size": None if is_directory else info.st_size,
                })
                if (
                    is_directory
                    and remaining > 1
                    and child.name.casefold() not in _IGNORED_DIRECTORIES
                ):
                    visit(child, remaining - 1)

        visit(directory, depth)
        value = {
            "workspace_id": self.scope.workspace_id,
            "trust": _TRUST_LABEL,
            "path": self.scope.relative_name(directory),
            "entries": entries,
            "coverage": {"directories_scanned": directories_scanned},
            "truncated": truncated,
        }
        return ToolOutput(value, {
            "workspace_id": self.scope.workspace_id,
            "path": self.scope.relative_name(directory),
            "entry_count": len(entries),
            "directories_scanned": directories_scanned,
            "truncated": truncated,
        })

    def read(self, arguments: dict[str, Any]) -> ToolOutput:
        self._arguments(arguments, {"path", "start_line", "max_lines"})
        relative, path = self.scope.resolve_file(arguments.get("path"))
        start_line = self._integer(
            arguments.get("start_line", 1), name="start_line", minimum=1, maximum=2_147_483_647
        )
        max_lines = self._integer(
            arguments.get("max_lines", self.scope.limits.max_read_lines),
            name="max_lines",
            minimum=1,
            maximum=self.scope.limits.max_read_lines,
        )
        snapshot = self.scope.read_snapshot(path)
        text = self._decode(snapshot)
        lines = text.splitlines()
        selected = lines[start_line - 1:start_line - 1 + max_lines]
        if any(len(line) > self.scope.limits.max_line_chars for line in selected):
            raise ToolError("line_too_long", "repository text line exceeds the output limit", denied=True)
        output_text = "\n".join(selected)
        if len(output_text) > self.scope.limits.max_output_chars:
            raise ToolError("output_too_large", "repository text exceeds the output limit", denied=True)
        end_line = start_line + len(selected) - 1 if selected else 0
        truncated = start_line > 1 or end_line < len(lines)
        next_start = end_line + 1 if end_line and end_line < len(lines) else None
        value = {
            "workspace_id": self.scope.workspace_id,
            "trust": _TRUST_LABEL,
            "path": relative.as_posix(),
            "sha256": snapshot.sha256,
            "size": snapshot.size,
            "total_lines": len(lines),
            "start_line": start_line,
            "end_line": end_line,
            "text": output_text,
            "truncated": truncated,
            "next_start_line": next_start,
        }
        return ToolOutput(value, {
            "workspace_id": self.scope.workspace_id,
            "path": relative.as_posix(),
            "sha256": snapshot.sha256,
            "size": snapshot.size,
            "start_line": start_line,
            "end_line": end_line,
            "truncated": truncated,
        })

    def _walk_files(self, directory: Path) -> Iterator[Path]:
        pending = [directory]
        while pending:
            current = pending.pop()
            relative_current = PurePosixPath(self.scope.relative_name(current))
            current = self.scope._resolve(relative_current, expected="directory")
            child_directories: list[Path] = []
            for child, info in self._children(current):
                if stat.S_ISREG(info.st_mode):
                    yield child
                elif child.name.casefold() not in _IGNORED_DIRECTORIES:
                    child_directories.append(child)
            pending.extend(reversed(child_directories))

    def search(self, arguments: dict[str, Any]) -> ToolOutput:
        self._arguments(arguments, {"query", "path"})
        query = arguments.get("query")
        if (
            not isinstance(query, str)
            or not query
            or len(query) > self.scope.limits.max_search_query_chars
            or "\x00" in query
            or "\n" in query
            or "\r" in query
        ):
            raise ToolError("invalid_argument", "query must be bounded, non-empty, single-line text", denied=True)
        _, directory = self.scope.resolve_directory(arguments.get("path", "."))
        matches: list[dict[str, Any]] = []
        files_scanned = 0
        files_considered = 0
        bytes_scanned = 0
        files_skipped = 0
        stop_reason: str | None = None

        for file_path in self._walk_files(directory):
            if files_considered >= self.scope.limits.max_search_files:
                stop_reason = "file_limit"
                break
            files_considered += 1
            try:
                relative_file = self.scope.relative_name(file_path)
                _, file_path = self.scope.resolve_file(relative_file)
                size = file_path.stat().st_size
            except (OSError, ToolError):
                files_skipped += 1
                continue
            if size > self.scope.limits.max_file_bytes:
                files_skipped += 1
                continue
            if bytes_scanned + size > self.scope.limits.max_search_bytes:
                stop_reason = "byte_limit"
                break
            try:
                snapshot = self.scope.read_snapshot(file_path)
            except ToolError:
                files_skipped += 1
                continue
            bytes_scanned += snapshot.size
            try:
                text = self._decode(snapshot)
            except ToolError:
                files_skipped += 1
                continue
            files_scanned += 1
            for line_number, line in enumerate(text.splitlines(), start=1):
                offset = 0
                while True:
                    column = line.find(query, offset)
                    if column < 0:
                        break
                    preview_start = max(0, column - self.scope.limits.max_preview_chars // 3)
                    preview = line[preview_start:preview_start + self.scope.limits.max_preview_chars]
                    matches.append({
                        "path": self.scope.relative_name(file_path),
                        "line": line_number,
                        "column": column + 1,
                        "preview": preview,
                        "preview_start_column": preview_start + 1,
                        "file_sha256": snapshot.sha256,
                    })
                    if len(matches) >= self.scope.limits.max_search_results:
                        stop_reason = "result_limit"
                        break
                    offset = column + max(1, len(query))
                if stop_reason == "result_limit":
                    break
            if stop_reason == "result_limit":
                break

        truncated = stop_reason is not None
        value = {
            "workspace_id": self.scope.workspace_id,
            "trust": _TRUST_LABEL,
            "path": self.scope.relative_name(directory),
            "matches": matches,
            "coverage": {
                "files_scanned": files_scanned,
                "files_considered": files_considered,
                "bytes_scanned": bytes_scanned,
                "files_skipped": files_skipped,
            },
            "truncated": truncated,
            "stop_reason": stop_reason,
        }
        return ToolOutput(value, {
            "workspace_id": self.scope.workspace_id,
            "path": self.scope.relative_name(directory),
            "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            "match_count": len(matches),
            "files_scanned": files_scanned,
            "files_considered": files_considered,
            "bytes_scanned": bytes_scanned,
            "files_skipped": files_skipped,
            "truncated": truncated,
            "stop_reason": stop_reason,
        })

    @staticmethod
    def _audit_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
        audited: dict[str, Any] = {}
        for key, value in sorted(arguments.items()):
            if key in {"path", "query"} and isinstance(value, str):
                audited[f"{key}_sha256"] = hashlib.sha256(value.encode("utf-8")).hexdigest()
                audited[f"{key}_chars"] = len(value)
            elif key in {"depth", "start_line", "max_lines"}:
                audited[key] = value
            else:
                audited["unsupported_argument_count"] = audited.get("unsupported_argument_count", 0) + 1
        return audited

    def register(self, registry: ToolRegistry) -> None:
        common_path = {
            "type": "string",
            "description": "Relative POSIX path inside the bound repository; never an absolute path.",
        }
        registry.register(
            "repo.list",
            self.list,
            spec=ToolSpec(
                "repo.list",
                "List bounded repository entries without following links.",
                {
                    "type": "object",
                    "properties": {
                        "path": common_path,
                        "depth": {"type": "integer", "minimum": 1, "maximum": self.scope.limits.max_list_depth},
                    },
                    "additionalProperties": False,
                },
                read_only=True,
            ),
            audit_arguments=self._audit_arguments,
        )
        registry.register(
            "repo.read",
            self.read,
            spec=ToolSpec(
                "repo.read",
                "Read a bounded slice of one UTF-8 repository file.",
                {
                    "type": "object",
                    "properties": {
                        "path": common_path,
                        "start_line": {"type": "integer", "minimum": 1},
                        "max_lines": {"type": "integer", "minimum": 1, "maximum": self.scope.limits.max_read_lines},
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
                read_only=True,
            ),
            audit_arguments=self._audit_arguments,
        )
        registry.register(
            "repo.search",
            self.search,
            spec=ToolSpec(
                "repo.search",
                "Search repository UTF-8 text using a bounded literal query, never regular expressions.",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "minLength": 1, "maxLength": self.scope.limits.max_search_query_chars},
                        "path": common_path,
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
                read_only=True,
            ),
            audit_arguments=self._audit_arguments,
        )
