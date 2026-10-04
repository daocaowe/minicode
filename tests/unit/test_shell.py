"""B6 ShellRunner 测试。"""

import asyncio
import sys

from minicode.tools.shell import ShellRunner


def test_shell_captures_stdout_stderr_and_exit_code() -> None:
    """命令应同时返回标准输出、错误输出和退出码。"""
    code = "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"
    result = asyncio.run(ShellRunner().run([sys.executable, "-c", code]))
    assert result.stdout.strip() == "out"
    assert result.stderr.strip() == "err"
    assert result.exit_code == 3
    assert result.timed_out is False


def test_shell_honors_working_directory(tmp_path) -> None:
    """命令应在调用方指定的工作目录执行。"""
    code = "import os; print(os.getcwd())"
    result = asyncio.run(ShellRunner().run([sys.executable, "-c", code], cwd=tmp_path))
    assert result.stdout.strip() == str(tmp_path)


def test_shell_truncates_large_output() -> None:
    """大输出应限制返回内容但保留完整字节数。"""
    code = "print('x' * 1000, end='')"
    result = asyncio.run(ShellRunner(output_limit=32).run([sys.executable, "-c", code]))
    assert len(result.stdout) == 32
    assert result.stdout_bytes == 1000
    assert result.stdout_truncated is True


def test_shell_timeout_terminates_process() -> None:
    """超时应终止进程并标记 timed_out。"""
    code = "import time; time.sleep(2)"
    result = asyncio.run(
        ShellRunner(kill_grace_seconds=0.05).run([sys.executable, "-c", code], timeout=0.05)
    )
    assert result.timed_out is True
    assert result.exit_code is not None


def test_shell_cancel_terminates_process() -> None:
    """取消事件应终止正在运行的进程。"""

    async def scenario():
        cancel = asyncio.Event()
        task = asyncio.create_task(
            ShellRunner().run([sys.executable, "-c", "import time; time.sleep(2)"], cancel=cancel)
        )
        await asyncio.sleep(0.05)
        cancel.set()
        return await task

    result = asyncio.run(scenario())
    assert result.cancelled is True
    assert result.exit_code is not None
