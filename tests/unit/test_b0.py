"""B0 acceptance tests."""

import subprocess
import sys
from pathlib import Path

import pytest

from minicode.errors import (
    ConfigurationError,
    MiniCodeError,
    PolicyDenied,
    ProviderError,
    RunAborted,
    ToolError,
)


def test_cli_help() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "minicode.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "MiniCode" in result.stdout


def test_cli_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "minicode.cli", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "minicode 0.1.0"


@pytest.mark.parametrize(
    "error_type",
    [ConfigurationError, ProviderError, ToolError, PolicyDenied, RunAborted],
)
def test_errors_have_stable_hierarchy(error_type: type[MiniCodeError]) -> None:
    assert issubclass(error_type, MiniCodeError)
    assert issubclass(error_type, Exception)


def test_temporary_directory_is_available(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    marker.write_text("ok", encoding="utf-8")
    assert marker.read_text(encoding="utf-8") == "ok"
