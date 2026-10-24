"""Proxies: stand-ins that control access to a real provider.

Same interface as a decorator, different intent: a decorator adds behavior,
while a proxy decides whether, when, or where the real object is reached.
"""

from typing import Any, Callable

from miniharness.providers.base import Provider
from miniharness.providers.registry import create_provider
from miniharness.types import LLMResponse, Message, ToolSpec


class LazyProvider:
    """Virtual proxy: builds the real provider on first use.

    Construction needs no API key, client, or network. A misconfigured provider
    fails on first use, or earlier if the caller calls materialize().
    Not thread-safe: two threads could both build the provider.
    """

    def __init__(self, factory: Callable[[], Provider], model: str | None = None):
        self._factory = factory
        self._model = model  # lets `.model` answer without building anything
        self._real: Provider | None = None

    @property
    def materialized(self) -> bool:
        return self._real is not None

    def materialize(self) -> Provider:
        if self._real is None:
            self._real = self._factory()
        return self._real

    @property
    def model(self) -> str:
        if self._real is None and self._model is not None:
            return self._model
        return self.materialize().model

    def complete(self, messages: list[Message], tools: dict[str, ToolSpec]) -> LLMResponse:
        return self.materialize().complete(messages, tools)


def lazy_provider(spec: str, **kwargs: Any) -> LazyProvider:
    """`create_provider`, deferred until first use."""
    _, _, model = spec.partition(":")
    return LazyProvider(lambda: create_provider(spec, **kwargs), model=model or None)
