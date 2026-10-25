"""State: a circuit breaker whose behavior depends on its current state.

    CLOSED --N consecutive failures--> OPEN --cooldown passes--> HALF_OPEN
      ^                                  ^                           |
      +------------ trial succeeds ------+------ trial fails --------+

Each state is its own class with its own hooks, so no method branches on
"which state am I in?". A transition is just assigning a new state object.
"""

import time
from typing import Callable, Iterator

from miniharness.errors import CircuitOpenError
from miniharness.providers.base import Provider
from miniharness.providers.streaming import stream_from
from miniharness.providers.wrappers import _Wrapper, transient_errors
from miniharness.types import Completed, LLMResponse, Message, StreamChunk, ToolSpec


class _State:
    """Three hooks around a call, instead of one `call(fn)`.

    A wrapped `fn()` returning a response can't cover a stream, whose outcome is
    only known after the last chunk. With hooks, `complete()` and `stream()`
    share the same state logic (DECISIONS.md D161).
    """

    name: str

    def admit(self, breaker: "CircuitBreaker") -> None:
        """Before the call: raise to reject it, or transition (the new state then decides)."""

    def succeeded(self, breaker: "CircuitBreaker") -> None: ...

    def failed(self, breaker: "CircuitBreaker") -> None: ...


class Closed(_State):
    """Normal operation: calls go through, consecutive failures are counted."""

    name = "closed"

    def __init__(self) -> None:
        self.failures = 0

    def succeeded(self, breaker):
        self.failures = 0

    def failed(self, breaker):
        self.failures += 1
        if self.failures >= breaker.threshold:
            breaker.transition(Open(breaker.clock()))


class Open(_State):
    """Failing fast: calls are rejected without touching the provider."""

    name = "open"

    def __init__(self, opened_at: float):
        self.opened_at = opened_at

    def admit(self, breaker):
        waited = breaker.clock() - self.opened_at
        if waited < breaker.cooldown_s:
            raise CircuitOpenError(
                f"{breaker.model} is failing; retrying in {breaker.cooldown_s - waited:.0f}s"
            )
        breaker.transition(HalfOpen())
        breaker.state.admit(breaker)


class HalfOpen(_State):
    """Probing: one trial call decides whether to close or re-open."""

    name = "half_open"

    def succeeded(self, breaker):
        breaker.transition(Closed())

    def failed(self, breaker):
        breaker.transition(Open(breaker.clock()))


class CircuitBreaker(_Wrapper):
    """Stops calling a provider that keeps failing, and probes it after a cooldown.

    Only transient errors trip the breaker. Configuration errors (bad key,
    unknown model) pass straight through: waiting won't fix them.
    """

    def __init__(
        self,
        inner: Provider,
        threshold: int = 3,
        cooldown_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        on: tuple[type[Exception], ...] | None = None,
    ):
        super().__init__(inner)
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.clock = clock
        self.on = on if on is not None else transient_errors()
        self.state: _State = Closed()
        self.transitions: list[tuple[str, str]] = []

    def transition(self, new: _State) -> None:
        self.transitions.append((self.state.name, new.name))
        self.state = new

    def complete(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> LLMResponse:
        self.state.admit(self)
        try:
            response = self.inner.complete(messages, tools)
        except self.on:
            self.state.failed(self)
            raise
        self.state.succeeded(self)
        return response

    def stream(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> Iterator[StreamChunk]:
        """Same as complete(); a stream abandoned before Completed counts as neither outcome.

        Success is recorded *at* Completed, before passing it on: a consumer may stop
        right there, and code after the last `yield` would then never run.
        """
        self.state.admit(self)
        try:
            for chunk in stream_from(self.inner, messages, tools):
                if isinstance(chunk, Completed):
                    self.state.succeeded(self)
                yield chunk
        except self.on:
            self.state.failed(self)
            raise
