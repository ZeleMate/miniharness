"""Helpers for the optional `stream()` half of a provider.

`stream()` is not part of the `Provider` protocol: a provider that only has
`complete()` still works everywhere, it just doesn't stream (DECISIONS.md D157).
"""

from typing import Iterable, Iterator

from miniharness.providers.base import Provider
from miniharness.types import Completed, LLMResponse, Message, StreamChunk, TextDelta, ToolSpec


def as_stream(response: LLMResponse) -> Iterator[StreamChunk]:
    """A finished response, replayed as a stream: all its text at once, then Completed.

    The text comes as one delta so consumers that only print tokens still show the answer.
    """
    if response.message.content:
        yield TextDelta(response.message.content)
    yield Completed(response)


def stream_from(provider: Provider, messages: list[Message], tools: dict[str, ToolSpec]) -> Iterator[StreamChunk]:
    """Stream from `provider` if it can, otherwise replay its `complete()` as a stream.

    A generator, so nothing is called until the first chunk is asked for.
    """
    stream = getattr(provider, "stream", None)
    if stream is None:
        yield from as_stream(provider.complete(messages, tools))
    else:
        yield from stream(messages, tools)


def collect(chunks: Iterable[StreamChunk]) -> LLMResponse:
    """Drain a stream and return its final response.

    Reads to the very end rather than returning at Completed: code a wrapper
    runs after its last `yield` (e.g. the breaker's bookkeeping) must get to run.
    """
    response = None
    for chunk in chunks:
        if isinstance(chunk, Completed):
            response = chunk.response
    if response is None:
        raise RuntimeError("Stream ended without a Completed chunk")
    return response
