# Chapter 9. Objects that change their own behavior

*Pattern: State. Code: `src/miniharness/providers/breaker.py`, `src/miniharness/lifecycle.py`.*

## Two problems, one pattern

Chapter 7 left a real problem behind: every agent turn retried a broken provider before falling back, paying
latency and money each time (D65). The fix, a **circuit breaker**, is an object whose behavior depends
entirely on its history. That's exactly the State pattern's territory: an object that behaves differently
depending on its current state, with each state's behavior kept in its own place instead of scattered
across `if self.mode == ...` checks.

The second use was more speculative, and the chapter said so up front: an explicit lifecycle for the agent
itself. `run()` worked fine as a loop. But explicit states would give the next chapter (Observer) clean
events to emit and chapter 11 (checkpoints) safe points to save and resume from. You chose to build both
(D79).

## The circuit breaker

The breaker wraps a provider and moves between three states:

```
CLOSED  --N consecutive failures-->  OPEN  --cooldown passes-->  HALF_OPEN
   ^                                   ^                            |
   +------------ trial succeeds -------+------ trial fails ---------+
```

- **Closed:** normal; calls go through and consecutive failures are counted.
- **Open:** failing fast; calls are rejected *instantly*, without touching the network.
- **Half-open:** probing; one trial call decides whether to close or re-open.

You chose GoF's form, one class per state (D80), over an Enum with a transition table. Each state class
has its own `call()`, and a transition is just assigning a new state object:

```python
class Closed:
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
```

An open breaker raises `CircuitOpenError`, which counts as a transient error (D81), so a `FallbackChain`
skips it straight away. The live check used an unreachable primary: the first turn made one real attempt
and opened the breaker; the next two turns skipped it instantly with no network call. D65 was fixed.

## Details that teach

**State-local data (D83).** The failure count belongs to the `Closed` state object, not to the breaker.
Entering `Closed` creates a fresh object, so the count resets automatically. No code anywhere has to
remember to reset it. States can carry exactly the data that only matters in that state: `Open` holds the
time it opened, and the agent's `ActingOnTools` state holds its pending tool calls.

**Only transient errors trip it (D82).** A bad key passes straight through without counting, consistent
with chapter 7's lesson. Waiting won't fix a configuration bug, so opening the circuit would only delay
the real error.

**An injected clock (D84).** The breaker takes a clock function, `time.monotonic` by default. Tests drive
time with a fake clock instead of sleeping, and a monotonic clock can't jump when the system clock changes.

**Lazy transitions (D86).** There's no timer thread. `Open` becomes `HalfOpen` on the next call after the
cooldown. Simpler, at the cost of the state still reading "open" until something calls it.

**Patterns combine (D85).** By intent the breaker is a protection proxy: it controls whether the provider
is reached. By implementation it's State. Neither label is wrong.

## The agent lifecycle

The agent became a small state machine:

```
idle --start()--> thinking --tool calls--> acting_on_tools --> thinking ...
                     +--answer--> done      (final)
                     +--stop----> stopped   (final)
```

`start()` and `step()` advance one transition at a time, and `run()` became "start, then step until done".
The states call the agent's existing Template Method hooks (D89): State decides *when* a step happens,
Template Method decides *how*. Subclasses that overrode `finish()` kept working, and all 106 earlier tests
passed without a single change, which is the best evidence a refactor preserved behavior.

Two things were deliberately left alone. Going over `max_steps` still raises an exception instead of ending
in a `stopped` state (D90), because changing what callers see is a behavior change, not a refactor. And
there's no `AwaitingHuman` state (D91): real asynchronous approval means pausing a run, returning control
and resuming hours later, possibly in another process, which needed chapter 11's checkpoints first.

## State vs Strategy

Both patterns swap an object to change behavior, so they're easy to confuse. The difference is *who swaps
it*. With Strategy, the **client** picks the object, and it rarely changes. With State, **the object
changes itself** as things happen. The provider an agent holds is a Strategy. The breaker's current state
is a State.

## The one thing to remember

**When behavior depends on history, give each state its own class and let the object change itself.**
State-local data then resets for free, and no method has to ask "which state am I in?".

## Questions to think about

- Add a `Paused` agent state that `step()` won't leave until `resume()` is called. What would it need to
  survive a process restart?
- The breaker counts consecutive failures, not a failure rate. When would a rate be the better trigger?
