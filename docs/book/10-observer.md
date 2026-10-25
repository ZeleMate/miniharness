# Chapter 10. Watching without touching

*Pattern: [Observer](https://refactoring.guru/design-patterns/observer). Code: `src/miniharness/events.py`, `src/miniharness/observers.py`.*

## The problem in the example script

Until this stage, the example printed tool calls only *after* the run finished, by scanning
`agent.messages`. You couldn't watch the agent work. Adding logging or tracing would have meant editing
the Agent, and every new kind of output would have meant editing it again.

Observer inverts that. The Agent *announces* what happened, and anyone interested subscribes. The Agent
never knows who is listening, or whether anyone is.

## Typed events on a bus

You chose typed event objects delivered through a bus (D93), over a GoF observer base class with
`on_state_change()`, `on_tool_call()` and so on:

```python
@dataclass(frozen=True)
class ToolCalled:
    call: ToolCall
    output: str
    decision: Decision | None   # which policy allowed or denied it

bus = EventBus()
bus.subscribe(ConsolePrinter())
bus.subscribe(JsonlTracer("run.jsonl"))
```

Subscribers are plain callables, and they pick the events they care about with `match`. The big
advantage: adding a new event type never changes an interface, so existing observers keep working. The
cost is discoverability. With hook methods, your editor lists them; with events, you read `events.py`.

The events are `RunStarted`, `StateChanged`, `ModelCalled` (with usage, cost and duration), `ToolCalled`
(with the policy decision) and `RunFinished`. Chapter 9's lifecycle paid off here: every transition already
went through one method, so state-change events came from a single place.

## Who emits what

Only the Toolbox knows a call's policy decision, so it emits `ToolCalled`. The Agent emits run, state and
model events. You chose one shared bus, injected into both (D94), so a single subscriber sees the whole
story in order.

A subtle decision made that robust: events are emitted from *framework* code, not from the overridable
hooks (D97). `ModelCalled` comes from the `Thinking` state, not from `think()`. A subclass that overrides
`think()` still produces events, so nobody has to remember to call `super()`.

## The defining property

**The subject never depends on its observers.** If a subscriber raises an exception (a full disk under the
trace file, a bug in a printer), the bus catches it, records it, warns, and carries on with the other
subscribers (D95). A broken observer can't break the run. That's tested with a handler that divides by
zero, and the run finishes normally.

The flip side is just as important: **observers can watch but can't veto** (D104). An observer hears about
an event after it happens. That's why the budget guard from chapter 6 is a proxy and not an observer: it
must stop a call *before* it happens. Observer is for reacting; controlling is a different job.

## Honest limits

Several costs were written down rather than hidden:

- Delivery is synchronous, in the emitting thread (D99): simple, ordered and deterministic in tests, but
  a slow observer slows the agent.
- Events carry the agent's own objects, and a frozen dataclass only freezes one level deep (D100). An
  observer *could* mutate a tool call's arguments.
- There's no event when a run crashes on an unexpected error (D101), so observers never see an ending.
- The Agent created its own bus by default but didn't share it with a Toolbox it built (D98). Forget to
  wire it yourself, and tool events silently never arrived. The last chapter finally fixed this.

## Two small stories

Making the Toolbox import the events module created a circular import (events needed a type from tools,
tools needed events). The fix was a `TYPE_CHECKING` import: `events.py` only needs that type as an
annotation, so it never imports it at runtime (D102). It's a common Python move worth recognizing.

And while editing the example, a bug from three stages earlier turned up: the fallback report looped with
`for provider, why in ...`, overwriting the `provider` variable that the cache summary read next. With
`--fallback --cache` and a failure, it would have crashed (D103). It was found only because the code was
being read for another reason, which is one argument for regularly rereading code you think is finished.

## The live run

A four-call run streamed every state, model call (tokens, cost, duration) and tool call to the console
*as it happened*, including a declined `write_file` marked "(by AskBeforeSideEffects)". The trace file got
17 lines, one per event, and chapter 14 builds a whole analysis tool on top of that file.

## The one thing to remember

**Subjects don't depend on observers, and observers can't control subjects.** If you need to stop
something, you need a proxy. If you need to react to it, you need an observer.

## Questions to think about

- Write a `Stats` observer that counts tool calls per tool and prints a summary on `RunFinished`. Did you
  touch the Agent?
- Which of D99–D101 would bite first in a production harness, and why?
