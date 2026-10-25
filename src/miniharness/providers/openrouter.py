import os
from typing import Any, Iterator

from openai import OpenAI

from miniharness.adapters.openai_chat import OpenAIChatAdapter
from miniharness.providers.registry import register_provider
from miniharness.types import LLMResponse, Message, StreamChunk, ToolSpec

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@register_provider("openrouter")
class OpenRouterProvider:
    def __init__(self, model: str | None = None, client: Any = None):
        self.model = model or os.environ.get(
            "OPENROUTER_MODEL", "deepseek/deepseek-chat"
        )
        if client is None:
            client = OpenAI(
                base_url=OPENROUTER_BASE_URL, api_key=os.environ["OPENROUTER_API_KEY"]
            )
        self.client = client
        self.adapter = OpenAIChatAdapter()

    def complete(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> LLMResponse:
        request = self.adapter.to_wire(messages, tools)
        response = self.client.chat.completions.create(model=self.model, **request)
        return self.adapter.from_wire(response)

    def stream(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> Iterator[StreamChunk]:
        request = self.adapter.to_wire(messages, tools)
        response = self.client.chat.completions.create(
            model=self.model,
            stream=True,
            stream_options={
                "include_usage": True
            },  # otherwise a stream reports no usage
            **request,
        )
        try:
            yield from self.adapter.from_stream(response)
        finally:
            # Runs when the consumer stops early, too: don't leave the connection open
            close = getattr(response, "close", None)
            if close is not None:
                close()
