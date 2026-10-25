"""Decorators: wrappers that are Providers themselves and add one behavior each.

Every wrapper takes an inner Provider, exposes the same `complete()` and
`model`, and delegates. Because the result is still a Provider, wrappers
stack, and the stacking order changes the behavior:

    DiskCache(Retry(BudgetGuard(UsageTracker(base))))

- the cache is outermost, so a cache hit costs nothing and skips the budget
- retry sits outside the budget, so every attempt is checked against it
- the tracker is innermost, so it sees every real call, including failed ones
  (a FallbackChain inside it adds what its skipped links were billed, D213)

Streaming (stage 15): `_Wrapper.stream()` goes through the wrapper's own
`complete()`, so a wrapper that doesn't know about streaming still applies
its behavior and just stops being live (DECISIONS.md D158). The wrappers
below override `stream()` to stay live. Forwarding to `inner.stream()` by
default would have silently skipped the budget.
"""

import hashlib
import json
import pickle
from dataclasses import replace
from pathlib import Path
from typing import Iterator

import anthropic
import openai

from miniharness.errors import BudgetExceeded, CircuitOpenError, MalformedResponseError
from miniharness.providers.base import Provider
from miniharness.providers.proxies import LazyProvider
from miniharness.providers.streaming import as_stream, stream_from
from miniharness.types import (
    Completed,
    LLMResponse,
    Message,
    StreamChunk,
    TextDelta,
    ToolSpec,
    Usage,
)


class _Wrapper:
    def __init__(self, inner: Provider):
        self.inner = inner

    @property
    def model(self) -> str:
        return self.inner.model

    def stream(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> Iterator[StreamChunk]:
        # Safe default: this wrapper's own complete(), replayed. Correct, but not live
        yield from as_stream(self.complete(messages, tools))


class UsageTracker(_Wrapper):
    """Records the usage of every call that reaches the provider."""

    def __init__(self, inner: Provider):
        super().__init__(inner)
        self.calls: list[Usage] = []

    def complete(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> LLMResponse:
        try:
            response = self.inner.complete(messages, tools)
        except MalformedResponseError as e:
            # A bad reply was still generated and billed
            self.calls.append(e.usage or Usage())
            raise
        self.calls.append(response.usage or Usage())
        return response

    def stream(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> Iterator[StreamChunk]:
        started = recorded = False
        try:
            for chunk in stream_from(self.inner, messages, tools):
                if isinstance(chunk, Completed):
                    self.calls.append(chunk.response.usage or Usage())
                    recorded = True
                started = True
                yield chunk
        except MalformedResponseError as e:
            self.calls.append(e.usage or Usage())
            recorded = True
            raise
        finally:
            if started and not recorded:
                # Abandoned or broken mid-stream: tokens were generated and billed,
                # but the usage never arrived. Unknown cost makes the budget fail closed.
                self.calls.append(Usage())

    @property
    def total(self) -> Usage:
        total = Usage(cost_usd=0.0)
        for usage in self.calls:
            total = total + usage
        return total


class BudgetGuard(_Wrapper):
    """Refuses to start a call once the tracked spend reaches the limit.

    Strictly a *protection proxy*, not a decorator: it never changes a response,
    it only decides whether the call happens (DECISIONS.md D72).

    Cost is only known after a call, so the last call can overshoot the limit.
    """

    def __init__(self, tracker: UsageTracker, limit_usd: float):
        super().__init__(tracker)
        self.tracker = tracker
        self.limit_usd = limit_usd

    def complete(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> LLMResponse:
        self._check()
        return self.inner.complete(messages, tools)

    def stream(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> Iterator[StreamChunk]:
        self._check()  # before the first token, like before a call
        yield from stream_from(self.inner, messages, tools)

    def _check(self) -> None:
        spent = self.tracker.total.cost_usd
        if spent is None:
            # Fail closed: a budget we can't measure is a budget we can't enforce
            raise BudgetExceeded(
                "Cost of an earlier call is unknown; can't enforce the budget"
            )
        if spent >= self.limit_usd:
            raise BudgetExceeded(f"Spent ${spent:.6f} of ${self.limit_usd:.6f}")


class Retry(_Wrapper):
    """Retries failures the SDKs can't see. (The SDKs already retry 429/5xx.)"""

    def __init__(
        self,
        inner: Provider,
        attempts: int = 3,
        on: tuple[type[Exception], ...] = (MalformedResponseError,),
    ):
        super().__init__(inner)
        self.attempts = attempts
        self.on = on
        self.retries = 0

    def complete(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> LLMResponse:
        for attempt in range(1, self.attempts + 1):
            try:
                return self.inner.complete(messages, tools)
            except self.on:
                if attempt == self.attempts:
                    raise
                self.retries += 1
        raise AssertionError("unreachable")

    def stream(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> Iterator[StreamChunk]:
        """Retries only while no text has been passed on: the consumer can't un-see tokens."""
        for attempt in range(1, self.attempts + 1):
            shown = False
            try:
                for chunk in stream_from(self.inner, messages, tools):
                    shown = shown or isinstance(chunk, TextDelta)
                    yield chunk
                return
            except self.on:
                if shown or attempt == self.attempts:
                    raise
                self.retries += 1


class DiskCache(_Wrapper):
    """Replays stored responses for identical requests. For development only.

    Uses pickle, which can run code on load: only point it at a directory
    you control.
    """

    def __init__(self, inner: Provider, path: Path | str, namespace: str | None = None):
        super().__init__(inner)
        self.path = Path(path)
        self._namespace = namespace
        self.hits = 0
        self.misses = 0

    def complete(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> LLMResponse:
        file = self.path / f"{self.key(messages, tools)}.pkl"
        if file.exists():
            self.hits += 1
            return pickle.loads(file.read_bytes())
        response = self.inner.complete(messages, tools)
        self.misses += 1
        self.path.mkdir(parents=True, exist_ok=True)
        file.write_bytes(pickle.dumps(response))
        return response

    def stream(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> Iterator[StreamChunk]:
        file = self.path / f"{self.key(messages, tools)}.pkl"
        if file.exists():
            self.hits += 1
            yield from as_stream(
                pickle.loads(file.read_bytes())
            )  # a hit replays all at once
            return
        for chunk in stream_from(self.inner, messages, tools):
            if isinstance(chunk, Completed):
                self.misses += 1
                self.path.mkdir(parents=True, exist_ok=True)
                file.write_bytes(pickle.dumps(chunk.response))
            yield chunk

    @property
    def namespace(self) -> str:
        # Resolved on first use: unwrapping a LazyProvider builds it
        if self._namespace is None:
            self._namespace = type(_innermost(self.inner)).__name__
        return self._namespace

    def key(self, messages: list[Message], tools: dict[str, ToolSpec]) -> str:
        payload = {
            "namespace": self.namespace,
            "model": self.model,
            "tools": tools,
            # `raw` is left out: it's provider-specific and derived from the rest
            "messages": [
                [
                    m.role,
                    m.content,
                    [[tc.id, tc.name, tc.arguments] for tc in m.tool_calls],
                    m.tool_call_id,
                ]
                for m in messages
            ],
        }
        blob = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()


def _innermost(provider: Provider) -> Provider:
    while True:
        if isinstance(provider, _Wrapper):
            provider = provider.inner
        elif isinstance(provider, LazyProvider):
            provider = provider.materialize()
        else:
            return provider


def transient_errors() -> tuple[type[Exception], ...]:
    """Errors that mean "this provider can't answer right now".

    Deliberately excludes auth, permission, bad-request and not-found errors:
    those are configuration bugs, and falling back would hide them.
    """
    return (
        anthropic.APIConnectionError,  # includes timeouts
        anthropic.RateLimitError,
        anthropic.InternalServerError,  # 5xx
        anthropic.OverloadedError,  # 529: its own class, not a subclass of InternalServerError
        openai.APIConnectionError,
        openai.RateLimitError,
        openai.InternalServerError,
        MalformedResponseError,
        CircuitOpenError,  # an open breaker: skip this provider
    )


class FallbackChain:
    """Chain of Responsibility over providers: the first one that answers wins.

    A provider passes the request on by failing with a transient error or by
    refusing. Configuration errors (bad key, unknown model) and StopRun (e.g. a
    budget) are never swallowed.

    A refusal or a malformed reply that is passed on was still billed, so its
    usage is added to the usage of the answer (or error) the chain finally
    returns. A tracker around the chain then counts the whole cost (D66, D213).
    """

    def __init__(
        self,
        providers: list[Provider],
        on: tuple[type[Exception], ...] | None = None,
        on_refusal: bool = True,
    ):
        if not providers:
            raise ValueError("FallbackChain needs at least one provider")
        self.providers = providers
        self.on = on if on is not None else transient_errors()
        self.on_refusal = on_refusal
        self.served_by: Provider | None = None
        self.failures: list[tuple[Provider, str]] = []  # why each link passed

    @property
    def model(self) -> str:
        return self.providers[0].model

    def complete(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> LLMResponse:
        last = len(self.providers) - 1
        billed: list[Usage] = []  # usage of the links that passed the request on
        for i, provider in enumerate(self.providers):
            try:
                response = provider.complete(messages, tools)
            except self.on as e:
                self.failures.append((provider, f"{type(e).__name__}: {e}"))
                if i == last:
                    _charge_earlier_links(e, billed)
                    raise
                _keep_billed(e, billed)
                continue
            if self.on_refusal and response.stop_reason == "refusal" and i < last:
                self.failures.append((provider, "refusal"))
                billed.append(response.usage or Usage())
                continue
            self.served_by = provider
            return _add_billed(response, billed)
        raise AssertionError("unreachable")

    def stream(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> Iterator[StreamChunk]:
        """Falls back only while no text has been passed on, for the same reason as Retry.

        A refusal is detected at Completed, so a refusal that already streamed its
        text is kept: switching then would show two answers glued together.
        """
        last = len(self.providers) - 1
        billed: list[Usage] = []  # usage of the links that passed the request on
        for i, provider in enumerate(self.providers):
            shown = False
            response = (
                None  # Completed is held back until we know we're keeping this answer
            )
            try:
                for chunk in stream_from(provider, messages, tools):
                    if isinstance(chunk, TextDelta):
                        shown = True
                        yield chunk
                    else:
                        response = chunk.response
            except self.on as e:
                self.failures.append((provider, f"{type(e).__name__}: {e}"))
                if shown or i == last:
                    _charge_earlier_links(e, billed)
                    raise
                _keep_billed(e, billed)
                continue
            if response is None:
                raise RuntimeError("Stream ended without a Completed chunk")
            if (
                self.on_refusal
                and response.stop_reason == "refusal"
                and i < last
                and not shown
            ):
                self.failures.append((provider, "refusal"))
                billed.append(response.usage or Usage())
                continue
            self.served_by = provider
            yield Completed(_add_billed(response, billed))
            return
        raise AssertionError("unreachable")


def _keep_billed(error: Exception, billed: list[Usage]) -> None:
    # Of the transient errors, only a malformed reply was generated (and billed)
    if isinstance(error, MalformedResponseError):
        billed.append(error.usage or Usage())


def _total(usage: Usage | None, billed: list[Usage]) -> Usage | None:
    if not billed:
        return usage
    total = usage or Usage()  # no usage reported: the cost stays unknown
    for earlier in billed:
        total = total + earlier
    return total


def _add_billed(response: LLMResponse, billed: list[Usage]) -> LLMResponse:
    return (
        replace(response, usage=_total(response.usage, billed)) if billed else response
    )


def _charge_earlier_links(error: Exception, billed: list[Usage]) -> None:
    """Let the error the chain gives up with carry the earlier links' usage, if it can.

    Only a MalformedResponseError carries usage. After another error (say the backup is
    down too), the cost of an earlier skipped refusal is lost (D213).
    """
    if billed and isinstance(error, MalformedResponseError):
        error.usage = _total(error.usage, billed)
