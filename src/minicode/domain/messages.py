"""Stable domain messages used by providers and the runtime."""

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolCall:
    """描述模型请求执行的一个工具调用。"""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    """表示发送给模型或由模型产生的一条消息。"""

    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """将消息转换为可发送给 Provider 的基础类型字典。"""
        result: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            result["tool_calls"] = [
                {"id": c.id, "name": c.name, "arguments": c.arguments} for c in self.tool_calls
            ]
        if self.tool_call_id is not None:
            result["tool_call_id"] = self.tool_call_id
        return result


@dataclass(frozen=True)
class LLMRequest:
    """封装一次模型请求及其工具和推理配置。"""

    messages: tuple[Message, ...]
    model: str
    tools: tuple[dict[str, Any], ...] = ()
    temperature: float | None = None
    reasoning_effort: str | None = None


@dataclass(frozen=True)
class LLMEvent:
    """表示 Provider 输出的一个标准化流式事件。"""

    type: str
    text: str = ""
    tool_call: ToolCall | None = None
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
