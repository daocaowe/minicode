"""安全的工作区文件工具。"""

from __future__ import annotations

import difflib
import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .registry import Tool


class WorkspaceError(ValueError):
    """表示路径或文件操作不满足工作区约束。"""


@dataclass(frozen=True)
class FileResult:
    """文件操作结果，包含内容摘要和可审计的变更详情。"""

    path: str
    content: str = ""
    details: dict[str, object] | None = None
    truncated: bool = False


class WorkspaceResolver:
    """将相对路径安全解析到固定工作区内。"""

    def __init__(self, workspace: str | Path, *, allow_absolute: bool = False) -> None:
        """创建解析器并固定工作区根目录。"""
        root = Path(workspace).expanduser().resolve()
        if not root.is_dir():
            raise WorkspaceError(f"workspace is not a directory: {workspace}")
        self.root = root
        self.allow_absolute = allow_absolute

    def resolve(self, path: str | Path) -> Path:
        """解析路径并拒绝越界路径和符号链接逃逸。"""
        candidate = Path(path)
        if candidate.is_absolute() and not self.allow_absolute:
            raise WorkspaceError("absolute paths are not allowed")
        lexical = (
            (self.root / candidate).resolve(strict=False)
            if not candidate.is_absolute()
            else candidate.resolve(strict=False)
        )
        try:
            lexical.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceError("path escapes workspace") from exc
        return lexical


class WorkspaceFiles:
    """提供 read、write、edit 三类工作区文件操作。"""

    def __init__(self, resolver: WorkspaceResolver) -> None:
        """创建绑定到指定工作区的文件工具。"""
        self.resolver = resolver

    def read(
        self,
        path: str,
        *,
        start_line: int | None = None,
        end_line: int | None = None,
        max_bytes: int | None = None,
        encoding: str = "utf-8",
    ) -> FileResult:
        """读取文本文件，可按行范围和字节数截断。"""
        target = self.resolver.resolve(path)
        try:
            raw = target.read_bytes()
        except OSError as exc:
            raise WorkspaceError(f"cannot read {path}: {exc}") from exc
        if bytes([0]) in raw:
            raise WorkspaceError(f"binary file is not supported: {path}")
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as exc:
            raise WorkspaceError(f"file is not valid {encoding}: {path}") from exc
        lines = text.splitlines(keepends=True)
        first = max((start_line or 1) - 1, 0)
        last = end_line if end_line is not None else len(lines)
        selected = "".join(lines[first:last])
        truncated = False
        if max_bytes is not None and len(selected.encode(encoding)) > max_bytes:
            selected = selected.encode(encoding)[:max_bytes].decode(encoding, errors="ignore")
            truncated = True
        return FileResult(
            path=str(target.relative_to(self.resolver.root)), content=selected, truncated=truncated
        )

    def write(
        self, path: str, content: str, *, overwrite: bool = True, encoding: str = "utf-8"
    ) -> FileResult:
        """通过同目录临时文件原子写入文本文件。"""
        target = self.resolver.resolve(path)
        if target.exists() and not overwrite:
            raise WorkspaceError(f"file already exists: {path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode(encoding)
        before = _sha256(target.read_bytes()) if target.exists() else None
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as temp:
                temp.write(data)
                temp.flush()
                os.fsync(temp.fileno())
            os.replace(temp_name, target)
        except OSError as exc:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise WorkspaceError(f"cannot write {path}: {exc}") from exc
        return FileResult(
            path=str(target.relative_to(self.resolver.root)),
            details={
                "before_sha256": before,
                "after_sha256": _sha256(data),
                "created": before is None,
            },
        )

    def edit(
        self, path: str, old_text: str, new_text: str, *, encoding: str = "utf-8"
    ) -> FileResult:
        """唯一替换旧文本并返回哈希和 unified diff，失败时不修改文件。"""
        target = self.resolver.resolve(path)
        try:
            original = target.read_text(encoding=encoding)
        except (OSError, UnicodeError) as exc:
            raise WorkspaceError(f"cannot read {path}: {exc}") from exc
        count = original.count(old_text)
        if count != 1:
            raise WorkspaceError(f"edit requires exactly one match, found {count}")
        updated = original.replace(old_text, new_text, 1)
        result = self.write(path, updated, overwrite=True, encoding=encoding)
        details = dict(result.details or {})
        details["diff"] = "".join(
            difflib.unified_diff(
                original.splitlines(True), updated.splitlines(True), fromfile=path, tofile=path
            )
        )
        details["operation"] = "edit"
        details["source"] = original
        details["updated"] = updated
        return FileResult(result.path, content=updated, details=details)

    def as_tools(self) -> tuple[Tool, Tool, Tool]:
        """将 read、write、edit 包装为 Agent 可注册调用的工具。"""
        return (
            Tool(
                "read",
                "Read a UTF-8 text file from the workspace",
                {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "start_line": {"type": "integer"},
                        "end_line": {"type": "integer"},
                        "max_bytes": {"type": "integer"},
                    },
                    "required": ["path"],
                },
                lambda args: _serialize_file_result(
                    self.read(
                        _required_string(args, "path"),
                        start_line=_optional_int(args, "start_line"),
                        end_line=_optional_int(args, "end_line"),
                        max_bytes=_optional_int(args, "max_bytes"),
                    )
                ),
            ),
            Tool(
                "write",
                "Create or replace a UTF-8 text file in the workspace",
                {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "overwrite": {"type": "boolean"},
                    },
                    "required": ["path", "content"],
                },
                lambda args: _serialize_file_result(
                    self.write(
                        _required_string(args, "path"),
                        _required_string(args, "content"),
                        overwrite=args.get("overwrite", True) is True,
                    )
                ),
            ),
            Tool(
                "edit",
                "Replace a unique text occurrence in a workspace file",
                {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old_text": {"type": "string"},
                        "new_text": {"type": "string"},
                    },
                    "required": ["path", "old_text", "new_text"],
                },
                lambda args: _serialize_file_result(
                    self.edit(
                        _required_string(args, "path"),
                        _required_string(args, "old_text"),
                        _required_string(args, "new_text"),
                    )
                ),
            ),
        )


def _sha256(data: bytes) -> str:
    """计算文件内容 SHA-256，用于变更审计。"""
    return hashlib.sha256(data).hexdigest()


def _required_string(args: dict[str, Any], name: str) -> str:
    """读取必填字符串参数并拒绝缺失或错误类型。"""
    value = args.get(name)
    if not isinstance(value, str):
        raise WorkspaceError(f"{name} must be a string")
    return value


def _optional_int(args: dict[str, Any], name: str) -> int | None:
    """读取可选整数参数，排除 bool 这类 int 子类型。"""
    value = args.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise WorkspaceError(f"{name} must be an integer")
    return value


def _serialize_file_result(result: FileResult) -> str:
    """将文件结果转换为可回传给模型的 JSON 文本。"""
    import json

    return json.dumps(
        {
            "path": result.path,
            "content": result.content,
            "details": result.details,
            "truncated": result.truncated,
        },
        ensure_ascii=False,
    )
