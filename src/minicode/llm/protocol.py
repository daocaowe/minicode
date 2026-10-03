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
    adapter: str = "fake"
    base_url: str | None = None
    api_key_env: str | None = None
    default_model: str = "gpt6.1sol"
    timeout_seconds: float = 120
    max_retries: int = 2
    headers: dict[str, str] = field(default_factory=dict)

    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env) if self.api_key_env else None

    def validate(self) -> None:
        if self.adapter != "fake" and not self.base_url:
            raise ConfigurationError("真实 Provider 必须配置 base_url")
        if self.adapter != "fake" and not self.api_key():
            raise ConfigurationError(f"未找到 API Key 环境变量: {self.api_key_env}")


class LLMProvider(Protocol):
    def stream(
        self, request: LLMRequest, cancel: asyncio.Event | None = None
    ) -> AsyncIterator[LLMEvent]: ...


class FakeProvider:
    def __init__(self, script: Iterable[LLMEvent] | None = None) -> None:
        self.script = tuple(
            script or (LLMEvent("text_delta", text="Fake response"), LLMEvent("response_end"))
        )
        self.requests: list[LLMRequest] = []

    async def stream(
        self, request: LLMRequest, cancel: asyncio.Event | None = None
    ) -> AsyncIterator[LLMEvent]:
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
    def __init__(self, config: ProviderConfig) -> None:
        config.validate()
        if not config.base_url:
            raise ConfigurationError("base_url is required")
        self.config = config

    async def stream(
        self, request: LLMRequest, cancel: asyncio.Event | None = None
    ) -> AsyncIterator[LLMEvent]:
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
                if chunk.get("usage"):
                    yield LLMEvent("usage", usage=chunk["usage"])
                if (chunk.get("choices") or [{}])[0].get("finish_reason"):
                    yield LLMEvent("response_end")
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"provider HTTP {exc.code}: {exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError(str(exc)) from exc


def provider_from_config(
    config: ProviderConfig, script: Iterable[LLMEvent] | None = None
) -> LLMProvider:
    if config.adapter == "fake":
        return FakeProvider(script)
    if config.adapter in {"openai", "openai-compatible"}:
        return OpenAICompatibleAdapter(config)
    raise ConfigurationError(f"unknown provider adapter: {config.adapter}")
