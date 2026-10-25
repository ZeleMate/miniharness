"""The Strategy interface: anything that can turn a conversation into a reply."""

from typing import Protocol

from miniharness.types import LLMResponse, Message, ToolSpec


class Provider(Protocol):
    model: str

    def complete(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> LLMResponse: ...
