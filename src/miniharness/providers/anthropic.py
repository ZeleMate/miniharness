import os
from typing import Any

from miniharness.adapters.anthropic_messages import AnthropicMessagesAdapter
from miniharness.providers.registry import register_provider
from miniharness.types import LLMResponse, Message, ToolSpec


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
        return self.adapter.from_wire(response)
