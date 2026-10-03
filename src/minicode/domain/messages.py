"""Stable domain messages used by providers and the runtime."""

from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
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
    messages: tuple[Message, ...]
    model: str
    tools: tuple[dict[str, Any], ...] = ()
    temperature: float | None = None
    reasoning_effort: str | None = None


@dataclass(frozen=True)
class LLMEvent:
    type: str
    text: str = ""
    tool_call: ToolCall | None = None
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
