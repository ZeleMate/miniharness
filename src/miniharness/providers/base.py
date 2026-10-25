"""The Strategy interface: anything that can turn a conversation into a reply."""

from typing import Protocol

from miniharness.types import LLMResponse, Message, ToolSpec


class Provider(Protocol):
    # Read-only, so a plain attribute and a wrapper's delegating property both qualify
    @property
    def model(self) -> str: ...

    def complete(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> LLMResponse: ...
