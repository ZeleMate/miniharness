"""State: a circuit breaker whose behavior depends on its current state.

    CLOSED --N consecutive failures--> OPEN --cooldown passes--> HALF_OPEN
      ^                                  ^                           |
      +------------ trial succeeds ------+------ trial fails --------+

Each state is its own class with its own `call()`, so no method branches on
"which state am I in?". A transition is just assigning a new state object.
"""

import time
from typing import Callable

from miniharness.errors import CircuitOpenError
from miniharness.providers.base import Provider
from miniharness.providers.wrappers import _Wrapper, transient_errors
from miniharness.types import LLMResponse, Message, ToolSpec


class _State:
    name: str

    def call(self, breaker: "CircuitBreaker", fn: Callable[[], LLMResponse]) -> LLMResponse:
        raise NotImplementedError


class Closed(_State):
    """Normal operation: calls go through, consecutive failures are counted."""

    name = "closed"

    def __init__(self) -> None:
        self.failures = 0

    def call(self, breaker, fn):
        try:
            response = fn()
        except breaker.on:
            self.failures += 1
            if self.failures >= breaker.threshold:
                breaker.transition(Open(breaker.clock()))
            raise
        self.failures = 0
        return response


class Open(_State):
    """Failing fast: calls are rejected without touching the provider."""

    name = "open"

    def __init__(self, opened_at: float):
        self.opened_at = opened_at

    def call(self, breaker, fn):
        waited = breaker.clock() - self.opened_at
        if waited < breaker.cooldown_s:
            raise CircuitOpenError(
                f"{breaker.model} is failing; retrying in {breaker.cooldown_s - waited:.0f}s"
            )
        breaker.transition(HalfOpen())
        return breaker.state.call(breaker, fn)


class HalfOpen(_State):
    """Probing: one trial call decides whether to close or re-open."""

    name = "half_open"

    def call(self, breaker, fn):
        try:
            response = fn()
        except breaker.on:
            breaker.transition(Open(breaker.clock()))
            raise
        breaker.transition(Closed())
        return response


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

    def complete(self, messages: list[Message], tools: dict[str, ToolSpec]) -> LLMResponse:
        return self.state.call(self, lambda: self.inner.complete(messages, tools))
