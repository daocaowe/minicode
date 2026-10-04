"""Docker 沙盒命令构造测试。"""

import asyncio

from minicode.tools.shell import DockerShellRunner


def test_docker_runner_builds_workspace_mount(monkeypatch, tmp_path) -> None:
    """Docker Runner 应把宿主工作区映射到 /workspace。"""
    captured = {}

    async def fake_run(self, command, *, cwd=None, timeout=None, cancel=None):
        captured["command"] = command
        return None

    monkeypatch.setattr("minicode.tools.shell.ShellRunner.run", fake_run)
    runner = DockerShellRunner(tmp_path)
    asyncio.run(runner.run(["pytest", "-q"], cwd=tmp_path))
    command = captured["command"]
    assert command[:6] == ["docker", "run", "--rm", "--network", "none", "-v"]
    assert "/workspace" in command
    assert command[-3:] == ["python:3.12-slim", "pytest", "-q"]
