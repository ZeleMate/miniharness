# Chapter 15. Answers that arrive over time

*Pattern: [Iterator](https://refactoring.guru/design-patterns/iterator). Code: `src/miniharness/providers/streaming.py`, `Agent.iter_run()`, `lifecycle.py`.*

## Waiting at a blank terminal

Everything so far returns only when it's finished. You wait in silence until the whole answer arrives, and
the only way to watch a run is to subscribe to its events (push). You can't drive a run from a plain `for`
loop, or stop it halfway through an answer.

## Two iterators

This stage builds two of them.

**A provider stream.** `provider.stream()` yields text chunks as they arrive, then exactly one `Completed`
chunk holding the full response (D156):

```python
for chunk in provider.stream(messages, tools):
    match chunk:
        case TextDelta(text=t):
            print(t, end="")
        case Completed(response=r):
            final = r
```

The alternative, a generator that *returns* the response, is elegant, but a plain `for` loop silently drops
a generator's return value, and only `yield from` would get it. The cost of the chosen form is that
consumers handle two chunk types; a `collect()` helper drains a stream for callers who only want the answer.

**A run iterator.** `agent.iter_run(task)` yields every event of the run as it happens: tokens, model calls,
tool calls, state changes. Tokens are a `TokenStreamed` event on the bus (D165), so there's one event
vocabulary, and `iter_run()` is built *on top of* the bus: a subscriber buffers what the bus pushes, and the
buffer is emptied every time the agent pauses. Pull and push see the same events in the same order, and a
test checks that with `==`.

## The pattern dissolves into the language

GoF's Iterator is a class with `has_next()` and `next()` that keeps traversal state outside the collection.
A Python **generator is that class, written for you by the compiler**. The paused stack frame holds the
traversal state, and `yield` is `next()`. This stage contains no hand-written `__next__` method.

Inside the agent, each lifecycle state has an `iter_step()` generator that pauses at every token and
*returns* the next state (D163). That makes streaming live, single-threaded and deterministic: no threads,
and stopping needs no cancellation protocol, because `break` simply stops asking for the next item.

## Iterator vs Observer: pull vs push

This is the chapter's central comparison. The events are the same; the direction of control is opposite.

- With **Observer** (push), the subject decides when you hear about something.
- With **Iterator** (pull), *you* decide when the subject continues.

Pull gives you backpressure and cancellation for free: the agent only advances when you ask, and `break`
stops it. Push reaches every listener, including sub-agents that run inside a tool call, where a generator
can't pause. In the pull view, a sub-agent's tokens arrive in one batch when the tool returns, while push
observers see them live.

## Where the patterns collide

Adding streaming touches everything built before, and some of the most instructive decisions come from the
friction:

- **Every decorator needs a streaming path (D158).** The tempting shortcut, forwarding `stream()` straight to
  the inner provider, would *silently skip the budget and the usage tracking*. Instead, every wrapper gets a
  safe default that goes through its own `complete()`, plus live overrides. The decorator stack only works
  if every path goes through every layer.
- **"Retry" stops meaning anything once the user has seen half an answer (D159).** You can't un-show tokens:
  retrying after "half" was printed would display "halfok". So retry and fallback only switch providers
  before the first text token.
- **The circuit breaker's states change shape (D161).** A stream's outcome is only known at the end, so the
  states expose `admit`, `succeeded` and `failed` hooks instead of wrapping one call.

## Bugs only pull can create

Two failure modes are worth understanding deeply, because they're about generators themselves.

**A ContextVar held across a `yield` leaks into the caller (D164).** Chapter 12's agent scope is a
ContextVar. If a generator sets it and then yields, the value stays set *in the consumer's code* while the
generator is paused, so the consumer's own events would be tagged as the agent's. The fix enters the scope
fresh around each resume and never holds it across a `yield`. Generators and context managers look like they
compose, and they don't quite.

**Code after a generator's last `yield` may never run (D172).** If the agent stops reading a stream as soon
as it sees `Completed`, and the circuit breaker records success *after* its loop, that code never runs.
Under an agent, a success then never resets the failure count, so two failures with a success between them
would open the breaker. With push, the producer decides when it's finished; with pull, the *consumer*
decides, and it can stop at any `yield`. A producer's cleanup belongs in `finally`, and its bookkeeping
before the last `yield`.

## Abandoned streams have unknown cost

Stopping the streaming example after twelve words leaves the agent resumable in the `thinking` state, with
the HTTP connection closed. But the run's cost becomes **unknown** (D160): usage data only arrives at the
end of a stream, and an abandoned stream never gets there. With chapter 6's fail-closed budget, one
interrupted stream blocks further calls. That's honest, and chapter 16 shows how it interacts with default
budgets. Anthropic streaming is tested against a fake client only (D170).

## The one thing to remember

**Pull and push are the same events with opposite control.** Push reaches everyone; pull gives the consumer
the power to pace and to stop, and with that power comes the duty to finish what producers need.

## Questions to think about

- Give the trace tree a `walk()` generator and rewrite the cost summary as a loop over it. What did you lose
  compared with the Visitor?
- Where in your own code does a generator do bookkeeping after its last `yield`?
