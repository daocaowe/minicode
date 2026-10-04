"""B5 工作区文件工具测试。"""

from pathlib import Path

import pytest

from minicode.tools.filesystem import WorkspaceError, WorkspaceFiles, WorkspaceResolver


def files(tmp_path: Path) -> WorkspaceFiles:
    """创建绑定到 pytest 临时工作区的文件工具。"""
    return WorkspaceFiles(WorkspaceResolver(tmp_path))


def test_read_supports_lines_and_truncation(tmp_path: Path) -> None:
    """读取应支持行范围和最大字节数。"""
    tool = files(tmp_path)
    tool.write("sample.txt", "one\ntwo\nthree\n")
    result = tool.read("sample.txt", start_line=2, end_line=3, max_bytes=4)
    assert result.content == "two\n"
    assert result.truncated is True


def test_write_is_atomic_and_reports_hashes(tmp_path: Path) -> None:
    """写入结果应包含创建状态和前后哈希。"""
    result = files(tmp_path).write("nested/file.txt", "hello")
    assert result.details is not None
    assert result.details["created"] is True
    assert result.details["before_sha256"] is None
    assert result.details["after_sha256"]


def test_edit_requires_unique_match_and_preserves_file_on_failure(tmp_path: Path) -> None:
    """匹配不是一次时应报错且保持原文件。"""
    tool = files(tmp_path)
    tool.write("app.py", "x = 1\nx = 1\n")
    with pytest.raises(WorkspaceError, match="exactly one match"):
        tool.edit("app.py", "x = 1", "x = 2")
    assert (tmp_path / "app.py").read_text() == "x = 1\nx = 1\n"


def test_edit_returns_diff_and_hashes(tmp_path: Path) -> None:
    """唯一替换应返回 unified diff 和哈希。"""
    tool = files(tmp_path)
    tool.write("app.py", "x = 1\n")
    result = tool.edit("app.py", "x = 1", "x = 2")
    assert "-x = 1" in result.details["diff"]  # type: ignore[index]
    assert result.details["before_sha256"] != result.details["after_sha256"]  # type: ignore[index]


def test_path_escape_and_binary_are_rejected(tmp_path: Path) -> None:
    """越界路径和二进制内容都必须拒绝。"""
    tool = files(tmp_path)
    with pytest.raises(WorkspaceError, match="escapes"):
        tool.read("../outside.txt")
    (tmp_path / "binary.bin").write_bytes(b"\x00\x01")
    with pytest.raises(WorkspaceError, match="binary"):
        tool.read("binary.bin")


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    """指向工作区外的符号链接不能被读取。"""
    outside = tmp_path.parent / "outside-b5.txt"
    outside.write_text("secret")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(WorkspaceError, match="escapes"):
        files(tmp_path).read("link.txt")
