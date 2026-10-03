"""Minimal sequential user -> model -> tools -> model loop."""

import asyncio
from collections.abc import AsyncIterator

from ..domain.messages import LLMEvent, LLMRequest, Message
from ..llm.protocol import LLMProvider
from ..tools.registry import ToolRegistry, ToolResult


class AgentLoop:
    def __init__(
        self, provider: LLMProvider, tools: ToolRegistry | None = None, max_turns: int = 8
    ) -> None:
        self.provider, self.tools, self.max_turns = provider, tools or ToolRegistry(), max_turns

    async def run(
        self, prompt: str, model: str = "gpt6.1sol", reasoning_effort: str | None = None
    ) -> AsyncIterator[LLMEvent | ToolResult]:
        messages = [Message("user", prompt)]
        for _ in range(self.max_turns):
            request = LLMRequest(
                tuple(messages), model, self.tools.declarations(), reasoning_effort=reasoning_effort
            )
            text, calls = "", []
            async for event in self.provider.stream(request):
                yield event
                if event.type == "text_delta":
                    text += event.text
                if event.tool_call:
                    calls.append(event.tool_call)
            messages.append(Message("assistant", text, tuple(calls)))
            if not calls:
                return
            for call in calls:
                result = self.tools.execute(call)
                messages.append(Message("tool", result.content, tool_call_id=result.tool_call_id))
                yield result
        yield LLMEvent("provider_error", error="maximum turns exceeded")


def run_sync(
    loop: AgentLoop, prompt: str, model: str, reasoning_effort: str | None = None
) -> list[LLMEvent | ToolResult]:
    async def collect() -> list[LLMEvent | ToolResult]:
        return [event async for event in loop.run(prompt, model, reasoning_effort)]

    return asyncio.run(collect())
