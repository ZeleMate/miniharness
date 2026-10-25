import os
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import anthropic

from miniharness.adapters.anthropic_messages import AnthropicMessagesAdapter
from miniharness.providers.registry import register_provider
from miniharness.types import (
    Completed,
    LLMResponse,
    Message,
    StreamChunk,
    ToolSpec,
    Usage,
)

# USD per million tokens (input, output). Thinking tokens bill as output.
# Simplified: ignores prompt-cache pricing and Haiku's higher rate above 100K input.
PRICES_PER_MTOK = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


@register_provider("anthropic")
class AnthropicProvider:
    def __init__(
        self, model: str | None = None, client: Any = None, max_tokens: int = 16000
    ):
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")
        if client is None:
            client = anthropic.Anthropic()
        self.client = client
        self.max_tokens = max_tokens
        self.adapter = AnthropicMessagesAdapter()

    def complete(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> LLMResponse:
        request = self.adapter.to_wire(messages, tools)
        response = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, **request
        )
        result = self.adapter.from_wire(response)
        if result.usage is not None:
            result.usage = self.price(result.usage)
        return result

    def stream(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> Iterator[StreamChunk]:
        request = self.adapter.to_wire(messages, tools)
        # The context manager closes the HTTP stream, even if the consumer stops early
        with self.client.messages.stream(
            model=self.model, max_tokens=self.max_tokens, **request
        ) as stream:
            for chunk in self.adapter.from_stream(stream):
                if isinstance(chunk, Completed) and chunk.response.usage is not None:
                    chunk.response.usage = self.price(chunk.response.usage)
                yield chunk

    def price(self, usage: Usage) -> Usage:
        prices = PRICES_PER_MTOK.get(self.model)
        if prices is None:
            return usage  # unknown model: cost stays None
        cost = (
            usage.input_tokens * prices[0] + usage.output_tokens * prices[1]
        ) / 1_000_000
        return replace(usage, cost_usd=cost)
