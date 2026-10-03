import asyncio

from minicode.domain.messages import LLMEvent, ToolCall
from minicode.llm.protocol import FakeProvider
from minicode.runtime.agent import AgentLoop
from minicode.tools.registry import ToolRegistry, echo_tool


def test_fake_provider_two_turn_agent_loop() -> None:
    provider = FakeProvider(
        [
            LLMEvent("tool_call_end", tool_call=ToolCall("1", "echo", {"text": "hello"})),
            LLMEvent("response_end"),
        ]
    )
    provider.script = (
        LLMEvent("tool_call_end", tool_call=ToolCall("1", "echo", {"text": "hello"})),
        LLMEvent("response_end"),
    )
    registry = ToolRegistry()
    registry.register(echo_tool())
    events = asyncio.run(collect(AgentLoop(provider, registry), "say hello"))
    assert any(getattr(e, "content", "") == '"hello"' for e in events)
    assert len(provider.requests) == 2


async def collect(loop: AgentLoop, prompt: str) -> list[object]:
    return [event async for event in loop.run(prompt)]
