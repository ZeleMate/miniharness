# Chapter 6. Layers around every call

*Pattern: [Decorator](https://refactoring.guru/design-patterns/decorator). Code: `src/miniharness/providers/wrappers.py`.*

## Behavior that belongs to every provider

Several features apply to *every* provider: track tokens and cost, stop at a budget, retry malformed
replies, cache responses during development. Building them into each provider duplicates code.
Subclassing every combination (`CachedRetryingTrackedOpenRouter`) explodes immediately.

Decorator solves this by wrapping: each wrapper takes a provider, *is* a provider, adds one behavior and
delegates the rest. Because the result is still a provider, wrappers stack:

```python
provider = DiskCache(Retry(BudgetGuard(UsageTracker(base))))
```

The Agent and the factory don't change at all. The alternative, a middleware list inside the Agent (D42),
would move the concern into the Agent and look more like the next chapter's pattern.

A naming trap: Python's `@decorator` syntax is a different idea. It wraps *functions at definition time*.
The GoF Decorator wraps *objects at runtime*. Same word, different tools.

## Facts before code

Before writing cost code, check what the API actually returns instead of guessing field names. OpenRouter
reports cost in US dollars in every response. Anthropic returns only token counts, so the Anthropic
provider prices tokens from a small table (D43, D52). Checking a real response first is a cheap habit that
prevents a whole category of bugs.

## Order is behavior

The central property of this stage: **decorators compose, but they don't commute** (D46). The same cache
in two positions behaves differently:

- **Cache outside the tracker:** a cache hit never reaches the tracker, so it costs nothing and doesn't
  count against the budget.
- **Cache inside the tracker:** the tracker sees the replayed response and counts its cost *again*.

Tests pin down both placements. The recommended order fixes every layer for a reason: the cache is
outermost so hits are free; retry sits outside the budget so every retry attempt is checked; the tracker is
innermost so it sees every real call, including failed ones.

## Decisions that come from thinking about failure

**Fail closed (D48).** If any call's cost is unknown, the budget stops the run rather than assuming $0. A
budget you can't measure is a budget you can't enforce. This "fail closed" stance reappears in almost every
later chapter.

**Failed replies still cost money (D49).** A reply with malformed tool-call JSON was still generated and
billed, so the error carries its usage and the tracker records it. Otherwise retries would be invisible
spend.

**Don't stack retries on retries (D50).** Both SDKs already retry rate limits and server errors twice.
Adding network retries on top would multiply them, up to nine calls for one request. `Retry` handles only
what the SDKs can't see: a reply that arrived but can't be used.

**The agent catches a base class (D45).** A budget stop raises `BudgetExceeded`, a subclass of `StopRun`,
and the Agent catches `StopRun` without knowing which wrapper raised it. The dependency points from the
wrappers to the Agent's contract, not the other way round, so any future wrapper can end a run cleanly.

## What to expect when you run it

Running the same task twice with `--cache` makes real calls the first time and none the second: every
response is a cache hit, at zero cost. A tiny `--budget` stops the agent after one call with
`[stopped: budget]`. Display formatting matters at small amounts: four decimal places would print a tiny
limit as `$0.0000`, which is why the message uses more precision.

The dev cache has a limit: it only helps until the first non-deterministic tool call. After `current_time`
runs, the conversation differs every time, so the cache key never matches again (D51). And this dev cache
is not the same thing as provider *prompt* caching: this one skips the API entirely, while prompt caching
makes a repeated prefix cheaper but still makes the call.

## The one thing to remember

**Decorators compose, but they don't commute.** When the order of wrappers changes the outcome, write the
order down in one place, and test it.

## Questions to think about

- Where should a `Timing` wrapper go to measure network time only? Where to include cache lookups?
- `BudgetGuard` never changes a response; it only decides whether the call happens. Is that really a
  Decorator? (Chapter 8 answers this.)
