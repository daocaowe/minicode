"""Tool protocol and deterministic registry."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..domain.messages import ToolCall


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], str]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def declarations(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in sorted(self._tools.values(), key=lambda x: x.name)
        )

    def execute(self, call: ToolCall) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(call.id, f"unknown tool: {call.name}", True)
        try:
            return ToolResult(call.id, tool.handler(call.arguments))
        except Exception as exc:  # tools must return errors to the loop
            return ToolResult(call.id, str(exc), True)


def echo_tool() -> Tool:
    return Tool(
        "echo",
        "Return the supplied text",
        {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        lambda args: json.dumps(args.get("text", ""), ensure_ascii=False),
    )
