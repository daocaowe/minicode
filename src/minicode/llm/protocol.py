"""Provider protocol and deterministic implementations."""

import asyncio
import json
import os
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..domain.messages import LLMEvent, LLMRequest
from ..errors import ConfigurationError, ProviderError


@dataclass(frozen=True)
class ProviderConfig:
    """保存 Provider 地址、认证环境变量和模型默认配置。"""

    adapter: str = "fake"
    base_url: str | None = None
    api_key_env: str | None = None
    default_model: str = "gpt6.1sol"
    timeout_seconds: float = 120
    max_retries: int = 2
    headers: dict[str, str] = field(default_factory=dict)

    def api_key(self) -> str | None:
        """从配置指定的环境变量读取 API Key。"""
        return os.getenv(self.api_key_env) if self.api_key_env else None

    def validate(self) -> None:
        """检查真实 Provider 所需的地址和认证配置。"""
        if self.adapter != "fake" and not self.base_url:
            raise ConfigurationError("真实 Provider 必须配置 base_url")
        if self.adapter != "fake" and not self.api_key():
            raise ConfigurationError(f"未找到 API Key 环境变量: {self.api_key_env}")


class LLMProvider(Protocol):
    """定义 Provider 向 Runtime 输出异步事件流的接口。"""

    def stream(
        self, request: LLMRequest, cancel: asyncio.Event | None = None
    ) -> AsyncIterator[LLMEvent]:
        """根据请求产生标准化 Provider 事件。"""
        ...


class FakeProvider:
    """按固定脚本输出事件、用于离线测试的 Provider。"""

    def __init__(self, script: Iterable[LLMEvent] | None = None) -> None:
        """创建事件脚本，可选脚本用于覆盖默认文本响应。"""
        self.script = tuple(
            script or (LLMEvent("text_delta", text="Fake response"), LLMEvent("response_end"))
        )
        self.requests: list[LLMRequest] = []

    async def stream(
        self, request: LLMRequest, cancel: asyncio.Event | None = None
    ) -> AsyncIterator[LLMEvent]:
        """记录请求并按顺序输出事件，取消时发出 aborted 错误。"""
        self.requests.append(request)
        script = (
            self.script
            if len(self.requests) == 1
            else (LLMEvent("text_delta", text="Fake response"), LLMEvent("response_end"))
        )
        for event in script:
            if cancel and cancel.is_set():
                yield LLMEvent("provider_error", error="aborted")
                return
            await asyncio.sleep(0)
            yield event


class OpenAICompatibleAdapter:
    """调用 OpenAI-compatible chat completions SSE 接口的适配器。"""

    def __init__(self, config: ProviderConfig) -> None:
        """校验配置并规范化中转站基础 URL。"""
        config.validate()
        if not config.base_url:
            raise ConfigurationError("base_url is required")
        normalized_url = config.base_url.strip().rstrip("/")
        if normalized_url.endswith("/chat/completions"):
            normalized_url = normalized_url[: -len("/chat/completions")]
        self.config = ProviderConfig(
            adapter=config.adapter,
            base_url=normalized_url,
            api_key_env=config.api_key_env,
            default_model=config.default_model,
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
            headers=config.headers,
        )

    async def stream(
        self, request: LLMRequest, cancel: asyncio.Event | None = None
    ) -> AsyncIterator[LLMEvent]:
        """发送请求并将 SSE 文本、usage 和结束信号转换为统一事件。"""
        base_url = self.config.base_url
        assert base_url is not None
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [m.to_dict() for m in request.messages],
            "stream": True,
        }
        if request.tools:
            payload["tools"] = list(request.tools)
        if request.reasoning_effort:
            payload["reasoning_effort"] = request.reasoning_effort
            payload["thinking"] = {"type": "enabled", "effort": request.reasoning_effort}
        headers = {"Content-Type": "application/json", **self.config.headers}
        if self.config.api_key():
            headers["Authorization"] = f"Bearer {self.config.api_key()}"
        try:
            response = await asyncio.to_thread(
                lambda: urllib.request.urlopen(
                    urllib.request.Request(
                        base_url.rstrip("/") + "/chat/completions",
                        data=json.dumps(payload).encode(),
                        headers=headers,
                    ),
                    timeout=self.config.timeout_seconds,
                )
            )
            tool_chunks: dict[int, dict[str, str]] = {}
            for raw in response:
                if cancel and cancel.is_set():
                    return
                line = raw.decode().strip()
                if not line.startswith("data:"):
                    continue
                value = line[5:].strip()
                if value == "[DONE]":
                    yield LLMEvent("response_end")
                    return
                chunk = json.loads(value)
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                if delta.get("content"):
                    yield LLMEvent("text_delta", text=delta["content"])
                for item in delta.get("tool_calls") or []:
                    index = int(item.get("index", 0))
                    function = item.get("function") or {}
                    state = tool_chunks.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    state["id"] += str(item.get("id") or "")
                    state["name"] += str(function.get("name") or "")
                    state["arguments"] += str(function.get("arguments") or "")
                    if state["arguments"].endswith("}"):
                        try:
                            arguments = json.loads(state["arguments"])
                        except json.JSONDecodeError:
                            arguments = None
                        if isinstance(arguments, dict):
                            from ..domain.messages import ToolCall

                            yield LLMEvent(
                                "tool_call_end",
                                tool_call=ToolCall(state["id"], state["name"], arguments),
                            )
                            del tool_chunks[index]
                if chunk.get("usage"):
                    yield LLMEvent("usage", usage=chunk["usage"])
                if (chunk.get("choices") or [{}])[0].get("finish_reason"):
                    yield LLMEvent("response_end")
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
            except OSError:
                detail = ""
            raise ProviderError(
                f"provider HTTP {exc.code} at {exc.url}: {exc.reason}; response={detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError(str(exc)) from exc


def provider_from_config(
    config: ProviderConfig, script: Iterable[LLMEvent] | None = None
) -> LLMProvider:
    """根据配置创建 Fake 或 OpenAI-compatible Provider。"""
    if config.adapter == "fake":
        return FakeProvider(script)
    if config.adapter in {"openai", "openai-compatible"}:
        return OpenAICompatibleAdapter(config)
    raise ConfigurationError(f"unknown provider adapter: {config.adapter}")
