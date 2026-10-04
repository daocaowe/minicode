"""Command-line entry point for MiniCode."""

import argparse
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from . import __version__
from .domain.messages import LLMEvent
from .llm.protocol import ProviderConfig, provider_from_config
from .runtime.agent import AgentLoop
from .tools.filesystem import WorkspaceFiles, WorkspaceResolver
from .tools.registry import ToolRegistry, ToolResult, echo_tool
from .tools.shell import DockerShellRunner, ShellRunner


def build_parser() -> argparse.ArgumentParser:
    """构造包含版本信息和 run 子命令的 CLI 解析器。"""
    parser = argparse.ArgumentParser(prog="minicode", description="MiniCode coding agent")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="run a task")
    run.add_argument("prompt", nargs="?")
    run.add_argument("--cwd", default=os.getcwd())
    run.add_argument(
        "--workspace", dest="cwd", default=argparse.SUPPRESS, help="项目文件夹路径；与 --cwd 同义"
    )
    run.add_argument("--sandbox", choices=["host", "docker"], default="host")
    run.add_argument("--docker-image", default="python:3.12-slim")
    run.add_argument("--json", action="store_true", dest="json_mode")
    run.add_argument("--no-session", action="store_true")
    run.add_argument("--max-turns", type=int, default=8)
    run.add_argument("--timeout", type=float, default=120)
    run.add_argument("--max-retries", type=int, default=2)
    run.add_argument("--provider", default=os.getenv("MINICODE_PROVIDER", "relay"))
    run.add_argument("--model", default=os.getenv("MINICODE_MODEL", "gpt6.1sol"))
    run.add_argument(
        "--reasoning-effort",
        choices=["low", "medium", "high", "xhigh"],
        default=os.getenv("MINICODE_REASONING_EFFORT"),
        help="推理强度：low/medium/high/xhigh",
    )
    run.add_argument(
        "--base-url", default=os.getenv("MINICODE_BASE_URL", "https://coloful-rose.com/v1")
    )
    run.add_argument("--api-key-env", default=os.getenv("MINICODE_API_KEY_ENV", "MINICODE_API_KEY"))
    return parser


def main() -> int:
    """解析命令并组装 Provider、工具注册表和 Agent Loop。"""
    args = build_parser().parse_args()
    if args.command == "run":
        adapter = "fake" if args.provider == "fake" else "openai-compatible"
        prompt = args.prompt or input().strip()
        config = ProviderConfig(
            adapter=adapter,
            base_url=args.base_url,
            api_key_env=args.api_key_env,
            default_model=args.model,
            timeout_seconds=args.timeout,
            max_retries=args.max_retries,
        )
        provider = provider_from_config(config)
        registry = ToolRegistry()
        registry.register(echo_tool())
        workspace_files = WorkspaceFiles(WorkspaceResolver(Path(args.cwd)))
        for tool in workspace_files.as_tools():
            registry.register(tool)
        shell = (
            DockerShellRunner(args.cwd, image=args.docker_image)
            if args.sandbox == "docker"
            else ShellRunner()
        )
        registry.register(shell.as_tool())
        return asyncio.run(_stream_cli(
            AgentLoop(provider, registry, max_turns=args.max_turns),
            prompt,
            args,
        ))
        displayed_tool_results: set[str] = set()
        assistant_buffer: list[str] = []

        def flush_assistant() -> None:
            """合并连续文本增量后一次性展示 assistant 消息。"""
            if assistant_buffer:
                print(f"\n[assistant {datetime.now().strftime('%H:%M:%S')}] ", end="")
                print("".join(assistant_buffer), end="")
                assistant_buffer.clear()

        for event in events:
            if args.json_mode:
                payload = {"type": getattr(event, "type", "tool_result"), "data": event.__dict__}
                print(json.dumps(payload, ensure_ascii=False, default=str))
                continue
            if isinstance(event, LLMEvent) and event.text:
                if event.text not in displayed_tool_results:
                    assistant_buffer.append(event.text)
            elif isinstance(event, ToolResult):
                flush_assistant()
                key = _tool_result_key(event.content)
                if key not in displayed_tool_results:
                    displayed_tool_results.add(key)
                    print(f"\n[tool {datetime.now().strftime('%H:%M:%S')}] ")
                    print(_format_tool_result(event.content))
        flush_assistant()
    return 0


async def _stream_cli(loop: AgentLoop, prompt: str, args: argparse.Namespace) -> int:
    """直接消费 Agent 事件流，让 assistant 文本即时显示。"""
    displayed: set[str] = set()
    assistant_started = False
    async for event in loop.run(prompt, args.model, args.reasoning_effort):
        if args.json_mode:
            payload = {"type": getattr(event, "type", "tool_result"), "data": event.__dict__}
            print(json.dumps(payload, ensure_ascii=False, default=str), flush=True)
            continue
        if isinstance(event, LLMEvent) and event.text:
            if event.text not in displayed:
                if not assistant_started:
                    print(f"\n[assistant {datetime.now().strftime('%H:%M:%S')}] ", end="", flush=True)
                    assistant_started = True
                print(event.text, end="", flush=True)
        elif isinstance(event, ToolResult):
            if assistant_started:
                print()
                assistant_started = False
            key = _tool_result_key(event.content)
            if key not in displayed:
                displayed.add(key)
                print(f"\n[tool {datetime.now().strftime('%H:%M:%S')}] ", flush=True)
                print(_format_tool_result(event.content), flush=True)
    if assistant_started:
        print()
    return 0


def _format_tool_result(content: str) -> str:
    """把工具结果压缩成摘要，并突出实际文件 diff。"""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return content
    if not isinstance(payload, dict):
        return str(payload)
    details = payload.get("details") or {}
    if not isinstance(details, dict):
        return str(payload)
    if details.get("operation") != "edit":
        if payload.get("path") and payload.get("content"):
            return f"文件已读取：{payload['path']}（{len(payload['content'])} 个字符）"
        if payload.get("stdout") is not None or payload.get("exit_code") is not None:
            return (
                f"命令执行完成：exit_code={payload.get('exit_code')}，"
                f"stdout={len(payload.get('stdout', ''))} 字符，"
                f"stderr={len(payload.get('stderr', ''))} 字符"
            )
        return content
    diff = details.get("diff", "")
    path = payload.get("path", "")
    return f"文件已修改：{path}\n[代码 Diff]\n{diff}"


def _tool_result_key(content: str) -> str:
    """按工具语义生成去重键，避免重复 read、shell 和 edit 输出。"""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return content
    if not isinstance(payload, dict):
        return content
    details = payload.get("details") or {}
    if not isinstance(details, dict):
        return content
    if details.get("operation") == "edit":
        return f"edit:{payload.get('path')}:{details.get('diff')}"
    if payload.get("path"):
        return f"read:{payload.get('path')}"
    if payload.get("exit_code") is not None:
        return f"shell:{payload.get('exit_code')}:{payload.get('stderr')}:{payload.get('stdout')}"
    return content


if __name__ == "__main__":
    raise SystemExit(main())
