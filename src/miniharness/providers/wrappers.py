"""Decorators: wrappers that are Providers themselves and add one behavior each.

Every wrapper takes an inner Provider, exposes the same `complete()` and
`model`, and delegates. Because the result is still a Provider, wrappers
stack, and the stacking order changes the behavior:

    DiskCache(Retry(BudgetGuard(UsageTracker(base))))

- the cache is outermost, so a cache hit costs nothing and skips the budget
- retry sits outside the budget, so every attempt is checked against it
- the tracker is innermost, so it sees every real call, including failed ones
"""

import hashlib
import json
import pickle
from pathlib import Path

from miniharness.errors import BudgetExceeded, MalformedResponseError
from miniharness.providers.base import Provider
from miniharness.types import LLMResponse, Message, ToolSpec, Usage


class _Wrapper:
    def __init__(self, inner: Provider):
        self.inner = inner

    @property
    def model(self) -> str:
        return self.inner.model


class UsageTracker(_Wrapper):
    """Records the usage of every call that reaches the provider."""

    def __init__(self, inner: Provider):
        super().__init__(inner)
        self.calls: list[Usage] = []

    def complete(self, messages: list[Message], tools: dict[str, ToolSpec]) -> LLMResponse:
        try:
            response = self.inner.complete(messages, tools)
        except MalformedResponseError as e:
            # A bad reply was still generated and billed
            self.calls.append(e.usage or Usage())
            raise
        self.calls.append(response.usage or Usage())
        return response

    @property
    def total(self) -> Usage:
        total = Usage(cost_usd=0.0)
        for usage in self.calls:
            total = total + usage
        return total


class BudgetGuard(_Wrapper):
    """Refuses to start a call once the tracked spend reaches the limit.

    Cost is only known after a call, so the last call can overshoot the limit.
    """

    def __init__(self, tracker: UsageTracker, limit_usd: float):
        super().__init__(tracker)
        self.tracker = tracker
        self.limit_usd = limit_usd

    def complete(self, messages: list[Message], tools: dict[str, ToolSpec]) -> LLMResponse:
        spent = self.tracker.total.cost_usd
        if spent is None:
            # Fail closed: a budget we can't measure is a budget we can't enforce
            raise BudgetExceeded("Cost of an earlier call is unknown; can't enforce the budget")
        if spent >= self.limit_usd:
            raise BudgetExceeded(f"Spent ${spent:.6f} of ${self.limit_usd:.6f}")
        return self.inner.complete(messages, tools)


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

    def complete(self, messages: list[Message], tools: dict[str, ToolSpec]) -> LLMResponse:
        for attempt in range(1, self.attempts + 1):
            try:
                return self.inner.complete(messages, tools)
            except self.on:
                if attempt == self.attempts:
                    raise
                self.retries += 1
        raise AssertionError("unreachable")


class DiskCache(_Wrapper):
    """Replays stored responses for identical requests. For development only.

    Uses pickle, which can run code on load: only point it at a directory
    you control.
    """

    def __init__(self, inner: Provider, path: Path | str, namespace: str | None = None):
        super().__init__(inner)
        self.path = Path(path)
        self.namespace = namespace or type(_innermost(inner)).__name__
        self.hits = 0
        self.misses = 0

    def complete(self, messages: list[Message], tools: dict[str, ToolSpec]) -> LLMResponse:
        file = self.path / f"{self.key(messages, tools)}.pkl"
        if file.exists():
            self.hits += 1
            return pickle.loads(file.read_bytes())
        response = self.inner.complete(messages, tools)
        self.misses += 1
        self.path.mkdir(parents=True, exist_ok=True)
        file.write_bytes(pickle.dumps(response))
        return response

    def key(self, messages: list[Message], tools: dict[str, ToolSpec]) -> str:
        payload = {
            "namespace": self.namespace,
            "model": self.model,
            "tools": tools,
            # `raw` is left out: it's provider-specific and derived from the rest
            "messages": [
                [m.role, m.content, [[tc.id, tc.name, tc.arguments] for tc in m.tool_calls], m.tool_call_id]
                for m in messages
            ],
        }
        blob = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()


def _innermost(provider: Provider) -> Provider:
    while isinstance(provider, _Wrapper):
        provider = provider.inner
    return provider


def _transient_errors() -> tuple[type[Exception], ...]:
    """Errors that mean "this provider can't answer right now".

    Deliberately excludes auth, permission, bad-request and not-found errors:
    those are configuration bugs, and falling back would hide them.
    """
    import anthropic
    import openai

    return (
        anthropic.APIConnectionError,  # includes timeouts
        anthropic.RateLimitError,
        anthropic.InternalServerError,  # 5xx, including overloaded
        openai.APIConnectionError,
        openai.RateLimitError,
        openai.InternalServerError,
        MalformedResponseError,
    )


class FallbackChain:
    """Chain of Responsibility over providers: the first one that answers wins.

    A provider passes the request on by failing with a transient error or by
    refusing. Configuration errors (bad key, unknown model) and StopRun (e.g. a
    budget) are never swallowed.
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
        self.on = on if on is not None else _transient_errors()
        self.on_refusal = on_refusal
        self.served_by: Provider | None = None
        self.failures: list[tuple[Provider, str]] = []  # why each link passed

    @property
    def model(self) -> str:
        return self.providers[0].model

    def complete(self, messages: list[Message], tools: dict[str, ToolSpec]) -> LLMResponse:
        last = len(self.providers) - 1
        for i, provider in enumerate(self.providers):
            try:
                response = provider.complete(messages, tools)
            except self.on as e:
                self.failures.append((provider, f"{type(e).__name__}: {e}"))
                if i == last:
                    raise
                continue
            if self.on_refusal and response.stop_reason == "refusal" and i < last:
                self.failures.append((provider, "refusal"))
                continue
            self.served_by = provider
            return response
        raise AssertionError("unreachable")
