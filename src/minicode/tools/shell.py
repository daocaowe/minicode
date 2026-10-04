"""受控的异步子进程执行工具。"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ShellResult:
    """保存命令执行状态、输出摘要和完整输出长度。"""

    command: tuple[str, ...]
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool
    cancelled: bool
    duration_seconds: float
    stdout_bytes: int
    stderr_bytes: int
    stdout_truncated: bool
    stderr_truncated: bool


class ShellRunner:
    """使用参数数组运行子进程，并处理输出、超时和取消。"""

    def __init__(self, *, output_limit: int = 16_000, kill_grace_seconds: float = 0.5) -> None:
        """设置模型可见输出上限和终止后的 kill 宽限期。"""
        self.output_limit = output_limit
        self.kill_grace_seconds = kill_grace_seconds

    async def run(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        timeout: float | None = None,
        cancel: asyncio.Event | None = None,
    ) -> ShellResult:
        """执行命令并持续消费 stdout/stderr，返回可解释的结果。"""
        if not command or any(not isinstance(item, str) or not item for item in command):
            raise ValueError("command must contain non-empty strings")
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=os.fspath(cwd) if cwd is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timed_out = False
        cancelled = False
        try:
            output = await self._consume(process, timeout=timeout, cancel=cancel)
            await process.wait()
        except TimeoutError:
            timed_out = True
            await self._terminate(process)
            output = await self._collect_after_stop(process)
        except _Cancelled:
            cancelled = True
            await self._terminate(process)
            output = await self._collect_after_stop(process)
        duration = time.monotonic() - started
        stdout, stderr, stdout_bytes, stderr_bytes = output
        return ShellResult(
            tuple(command),
            stdout,
            stderr,
            process.returncode,
            timed_out,
            cancelled,
            duration,
            stdout_bytes,
            stderr_bytes,
            len(stdout.encode()) < stdout_bytes,
            len(stderr.encode()) < stderr_bytes,
        )

    async def _consume(
        self,
        process: asyncio.subprocess.Process,
        *,
        timeout: float | None,
        cancel: asyncio.Event | None,
    ) -> tuple[str, str, int, int]:
        """并发读取两个输出流，并在超时或取消时中断等待。"""

        async def read(stream: asyncio.StreamReader | None) -> tuple[str, int]:
            data = await stream.read() if stream else b""
            return data.decode("utf-8", errors="replace"), len(data)

        task = asyncio.gather(read(process.stdout), read(process.stderr))
        cancel_task = asyncio.create_task(cancel.wait()) if cancel else None
        try:
            waits: set[Any] = {task}
            if cancel_task:
                waits.add(cancel_task)
            done, _ = await asyncio.wait(
                waits, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if cancel_task and cancel_task in done and cancel_task.result():
                raise _Cancelled
            if task not in done:
                raise TimeoutError
            (stdout, stdout_bytes), (stderr, stderr_bytes) = task.result()
            limited_stdout, _ = self._limit(stdout, stdout_bytes)
            limited_stderr, _ = self._limit(stderr, stderr_bytes)
            return limited_stdout, limited_stderr, stdout_bytes, stderr_bytes
        finally:
            if cancel_task:
                cancel_task.cancel()

    async def _terminate(self, process: asyncio.subprocess.Process) -> None:
        """先温和终止进程，超出宽限期后强制结束。"""
        if process.returncode is not None:
            return
        if os.name == "nt":
            process.terminate()
        else:
            process.send_signal(signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=self.kill_grace_seconds)
        except TimeoutError:
            process.kill()
            await process.wait()

    async def _collect_after_stop(
        self, process: asyncio.subprocess.Process
    ) -> tuple[str, str, int, int]:
        """终止后继续消费管道，避免子进程输出堵塞或泄漏。"""
        stdout_stream = process.stdout
        stderr_stream = process.stderr
        if stdout_stream is None or stderr_stream is None:
            return "", "", 0, 0
        stdout, stderr = await asyncio.gather(stdout_stream.read(), stderr_stream.read())
        limited_stdout, _ = self._limit(stdout.decode(errors="replace"), len(stdout))
        limited_stderr, _ = self._limit(stderr.decode(errors="replace"), len(stderr))
        return limited_stdout, limited_stderr, len(stdout), len(stderr)

    def _limit(self, text: str, size: int) -> tuple[str, int]:
        """保留输出前缀供模型查看，同时记录完整字节数。"""
        encoded = text.encode()
        return (encoded[: self.output_limit].decode(errors="replace"), size)

    def as_tool(self):
        """创建供 Agent 调用的异步 shell 工具。"""
        from .registry import Tool

        async def handler(args):
            command = args.get("command")
            if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
                raise ValueError("command must be a string array")
            result = await self.run(command, cwd=args.get("cwd"), timeout=args.get("timeout"))
            return json.dumps(
                {
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "exit_code": result.exit_code,
                    "timed_out": result.timed_out,
                    "cancelled": result.cancelled,
                },
                ensure_ascii=False,
            )

        return Tool(
            "shell",
            "Run a command in the workspace",
            {
                "type": "object",
                "properties": {
                    "command": {"type": "array", "items": {"type": "string"}},
                    "cwd": {"type": "string"},
                    "timeout": {"type": "number"},
                },
                "required": ["command"],
            },
            handler,
        )


class DockerShellRunner(ShellRunner):
    """在一次性 Docker 容器中执行命令，并挂载指定工作区。"""

    def __init__(
        self, workspace: str | Path, *, image: str = "python:3.12-slim", **kwargs: Any
    ) -> None:
        """配置只读网络、工作区挂载和容器基础镜像。"""
        super().__init__(**kwargs)
        self.workspace = Path(workspace).resolve()
        if not self.workspace.is_dir():
            raise ValueError(f"workspace is not a directory: {workspace}")
        self.image = image

    async def run(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        timeout: float | None = None,
        cancel: asyncio.Event | None = None,
    ) -> ShellResult:
        """通过 docker run 执行命令，容器退出后保留宿主工作区修改。"""
        container_cwd = "/workspace"
        if cwd:
            requested = Path(cwd).resolve()
            try:
                relative = requested.relative_to(self.workspace)
            except ValueError as exc:
                raise ValueError("docker shell cwd must stay inside workspace") from exc
            container_cwd = (
                "/workspace" if str(relative) == "." else f"/workspace/{relative.as_posix()}"
            )
        docker_command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            f"{self.workspace}:/workspace",
            "-w",
            container_cwd,
            self.image,
            *command,
        ]
        return await super().run(docker_command, timeout=timeout, cancel=cancel)


class _Cancelled(Exception):
    """内部取消信号，不暴露给调用方。"""
