"""Proxies: stand-ins that control access to a real provider.

Same interface as a decorator, different intent: a decorator adds behavior,
while a proxy decides whether, when, or where the real object is reached.
"""

from collections.abc import Callable, Iterator
from typing import Any

from miniharness.providers.base import Provider
from miniharness.providers.registry import ProviderRegistry, resolve
from miniharness.providers.streaming import stream_from
from miniharness.types import LLMResponse, Message, StreamChunk, ToolSpec


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

    def complete(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> LLMResponse:
        return self.materialize().complete(messages, tools)

    def stream(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> Iterator[StreamChunk]:
        yield from stream_from(self.materialize(), messages, tools)


def lazy_provider(
    spec: str, *, registry: ProviderRegistry | None = None, **kwargs: Any
) -> LazyProvider:
    """`registry.create(spec)`, deferred until first use.

    The registry is chosen now, not at first use (D205): the spec means what it
    meant when the caller wrote it.
    """
    _, _, model = spec.partition(":")
    providers = resolve(registry)
    return LazyProvider(lambda: providers.create(spec, **kwargs), model=model or None)
