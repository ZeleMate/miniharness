"""The recommended provider stack, built in one place.

Stage 16 (Facade): D54 kept the wrapper stack hand-built so its order (D46)
stayed visible. Now it's built in more than one place (the Harness facade,
examples/team.py), so the recipe moves here. Like `default_prompt()` in
stage 4, this is a Director: a function that knows the order, not a class.

The returned `Stack` keeps handles to the layers callers read afterwards
(usage, cache hits, fallbacks), so nobody has to dig through `.inner.inner`.
"""

from dataclasses import dataclass
from pathlib import Path

from miniharness.providers.base import Provider
from miniharness.providers.breaker import CircuitBreaker
from miniharness.providers.proxies import lazy_provider
from miniharness.providers.registry import ProviderRegistry, resolve
from miniharness.providers.wrappers import BudgetGuard, DiskCache, FallbackChain, Retry, UsageTracker


@dataclass
class Stack:
    provider: Provider  # the outermost layer: give this to an Agent
    tracker: UsageTracker  # every real call, for cost reports
    base: Provider  # what the tracker wraps: the model, or the fallback chain
    chain: FallbackChain | None = None  # set with fallback=; read `.failures`
    cache: DiskCache | None = None  # set with cache=; read `.hits` / `.misses`


def build_stack(
    model: str | Provider,
    *,
    budget: float | None = None,
    cache: str | Path | None = None,
    fallback: str | Provider | None = None,
    retries: int = 3,
    registry: ProviderRegistry | None = None,
) -> Stack:
    """`DiskCache(Retry(BudgetGuard(UsageTracker(base))))`, leaving out what isn't asked for.

    `model` is a `"provider:model"` spec (built now, so a bad config fails at
    startup) or a ready Provider. A `fallback` spec is built lazily: its key is
    only needed if the main provider fails. The breaker stops retrying a
    failing main provider on every turn. Both specs are looked up in
    `registry` (the default registry unless one is injected).
    """
    providers = resolve(registry)
    base = providers.create(model) if isinstance(model, str) else model
    chain = None
    if fallback is not None:
        backup = lazy_provider(fallback, registry=providers) if isinstance(fallback, str) else fallback
        base = chain = FallbackChain([CircuitBreaker(base), backup])
    tracker = UsageTracker(base)  # innermost: sees every real call, failed ones too
    guarded = tracker if budget is None else BudgetGuard(tracker, limit_usd=budget)
    provider: Provider = Retry(guarded, attempts=retries)  # outside the guard: each attempt is checked
    disk = None
    if cache is not None:
        provider = disk = DiskCache(provider, cache)  # outermost: hits are free and skip the budget
    return Stack(provider=provider, tracker=tracker, base=base, chain=chain, cache=disk)
