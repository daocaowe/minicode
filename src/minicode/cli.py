"""Command-line entry point for MiniCode."""

import argparse
import os

from . import __version__
from .domain.messages import LLMEvent
from .llm.protocol import ProviderConfig, provider_from_config
from .runtime.agent import AgentLoop, run_sync
from .tools.registry import ToolRegistry, ToolResult, echo_tool


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(prog="minicode", description="MiniCode coding agent")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")
    run = sub.add_parser("run", help="run a task")
    run.add_argument("prompt")
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
    """Run the MiniCode command-line interface."""
    args = build_parser().parse_args()
    if args.command == "run":
        adapter = "fake" if args.provider == "fake" else "openai-compatible"
        config = ProviderConfig(
            adapter=adapter,
            base_url=args.base_url,
            api_key_env=args.api_key_env,
            default_model=args.model,
        )
        provider = provider_from_config(config)
        registry = ToolRegistry()
        registry.register(echo_tool())
        events = run_sync(
            AgentLoop(provider, registry), args.prompt, args.model, args.reasoning_effort
        )
        for event in events:
            if isinstance(event, LLMEvent) and event.text:
                print(event.text, end="")
            elif isinstance(event, ToolResult):
                print(event.content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
