import os
from dataclasses import replace
from typing import Any

from miniharness.adapters.anthropic_messages import AnthropicMessagesAdapter
from miniharness.providers.registry import register_provider
from miniharness.types import LLMResponse, Message, ToolSpec, Usage

# USD per million tokens (input, output). Thinking tokens bill as output.
# Simplified: ignores prompt-cache pricing and Haiku's higher rate above 100K input.
PRICES_PER_MTOK = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


@register_provider("anthropic")
class AnthropicProvider:
    def __init__(self, model: str | None = None, client: Any = None, max_tokens: int = 16000):
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-opus-5-5")
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client
        self.max_tokens = max_tokens
        self.adapter = AnthropicMessagesAdapter()

    def complete(self, messages: list[Message], tools: dict[str, ToolSpec]) -> LLMResponse:
        request = self.adapter.to_wire(messages, tools)
        response = self.client.messages.create(model=self.model, max_tokens=self.max_tokens, **request)
        result = self.adapter.from_wire(response)
        if result.usage is not None:
            result.usage = self.price(result.usage)
        return result

    def price(self, usage: Usage) -> Usage:
        prices = PRICES_PER_MTOK.get(self.model)
        if prices is None:
            return usage  # unknown model: cost stays None
        cost = (usage.input_tokens * prices[0] + usage.output_tokens * prices[1]) / 1_000_000
        return replace(usage, cost_usd=cost)
