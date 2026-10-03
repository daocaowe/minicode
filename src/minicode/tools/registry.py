"""Tool protocol and deterministic registry."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..domain.messages import ToolCall


@dataclass(frozen=True)
class ToolResult:
    """保存工具调用结果，并通过调用 ID 与请求关联。"""

    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class Tool:
    """描述一个可注册工具及其输入 schema 和执行函数。"""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], str]


class ToolRegistry:
    """注册工具、生成声明并顺序执行工具调用。"""

    def __init__(self) -> None:
        """创建空注册表。"""
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册工具；重复名称会抛出 ValueError。"""
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def declarations(self) -> tuple[dict[str, Any], ...]:
        """按名称排序返回 OpenAI-compatible 工具声明。"""
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
        """执行调用并将未知工具或处理异常转换为错误结果。"""
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(call.id, f"unknown tool: {call.name}", True)
        try:
            return ToolResult(call.id, tool.handler(call.arguments))
        except Exception as exc:  # tools must return errors to the loop
            return ToolResult(call.id, str(exc), True)


def echo_tool() -> Tool:
    """创建用于演示和 V0 验收的 echo 工具。"""
    return Tool(
        "echo",
        "Return the supplied text",
        {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        lambda args: json.dumps(args.get("text", ""), ensure_ascii=False),
    )
