# Chapter 19. Several things at once

*No new pattern: concurrency built on [Command](https://refactoring.guru/design-patterns/command). Code:
`src/miniharness/tools/toolbox.py`, `tests/test_concurrency.py`.*

## An assumption written down in chapter 5

Models often ask for several tools in one turn: read three files, then answer. Since chapter 5 the Toolbox
runs them one after another, so the turn takes as long as all three added up. That's deliberate. A model can
send `write_file` and `read_file` for the same path *in the same turn*, which only works if the calls run in
order; running them at once would be a race. So D39 says: sequential, in the model's order, revisit when
tools get slow.

D39 then quietly becomes load-bearing. The trace builder pairs a sub-agent's run with the parent's *next*
tool call (D148). The lazy proxy (D78) and the breaker's half-open state (D87) are declared "fine while the
harness is sequential". The pull view of chapter 15 never yields between tools (D171). An assumption that's
written down is one you can audit: search the design rationale for D39 and you have the list of things that
could break.

## Four decisions before any code

**Which calls run together (D215).** Every call at once would bring D39's race straight back. A new per-tool
opt-in flag would be the most precise, but nothing would get faster until every tool author opted in. The
middle path: cut the turn into groups in the model's order. A run of consecutive read-only calls is one
group; every call with side effects is a group of its own.

```
calls:  read a, read b, write c, read c, read d
groups: {read a, read b} -> {write c} -> {read c, read d}
```

`read c` always sees the write, exactly as before. The grouping uses `side_effects`, the flag every tool has
set correctly since chapter 5, because the default policy and undo already depend on it. No tool has to
change.

**Leaf tools first (D216).** Read-only sub-agents look like the obvious win: parallel research helpers. But
two sub-runs at once put two runs' events on one bus at the same time, and the trace builder pairs by
position. The shared provider stack has check-then-act races: `BudgetGuard` checks the spend and *then*
calls, so two runs could both pass the check and overspend together. Doing it properly means run ids on
events, a new trace format, and locks in three wrappers. So `AgentTool` sets a `thread_safe = False` flag and
stays sequential; parallel sub-agents are the recorded next step.

**Threads, not asyncio (D217).** Every tool, every provider and `Agent.step()` is synchronous. Asyncio would
mean `async def` all the way up, or `asyncio.to_thread()` around each tool, which is a thread pool with an
event loop on top. The tools worth overlapping wait on files and the network, and Python releases the GIL
while a thread waits, so plain threads give the real speedup.

**Events in the model's order (D218).** A group's `ToolCalled` events are emitted after the group finishes,
in call order, on the agent's own thread. Traces stay deterministic, and no observer ever runs on two
threads at once, so the bus, the console printer and the JSONL tracer need no locks. The cost: a slow call
delays the events of the fast ones in its group.

## The shape

```python
def execute_all(self, calls):
    outputs = []
    for group in self._groups(calls):          # in the model's order
        outputs += self._run_group(group)
    return outputs

def _run_group(self, calls):
    decisions = [self._decide(c) for c in calls]   # here, in order (D219)
    commands = {...allowed calls...}
    errors = self._run(commands)                   # the only part on other threads
    ...report each call in order: history, ToolCalled, output...
```

This is where chapter 5 pays off. A `ToolCommand` already holds everything needed to run one call, so
handing calls to a pool is `pool.map()` over commands. Nothing about a tool has to know it might run on
another thread.

Two smaller decisions shape `_run_group`. Policies decide on the agent's thread, in order, *before* the group
runs (D219): `MaxCalls` keeps a counter that threads would race, and an approver may be a human at
`input()`, who shouldn't get questions in random order from random threads. And `execute(call)` is just
`execute_all([call])[0]`, so there is one code path, not two that could drift apart.

It's opt-in, like streaming (D221): `Toolbox(max_workers=4)`, or `Harness(tool_workers=4)` through the
facade. With the default of one worker there are no groups at all: each call is decided, run and reported
before the next one is looked at. (Grouping anyway and only skipping the pool would delay a read's
`ToolCalled` until the next read had run; a test pins the strict order.)

## The trap: threads don't inherit the context

Chapter 12 puts "which agent is running" in a ContextVar, and chapter 18 explains why it stays: each thread
sees its own value. That's exactly the problem. A thread pool's workers start with an *empty* context, so a
tool running in the pool sees no agent at all (`current_depth()` returns -1), and anything it emits would be
tagged with no agent at depth 0.

The fix is one line with two details that matter (D220):

```python
contexts = [contextvars.copy_context() for _ in commands]  # on *this* thread
pool.map(lambda ctx, command: ctx.run(_attempt, command), contexts, commands)
```

The copy is made on the calling thread; copying inside the worker would copy the worker's empty context. And
it's one copy *per call*: a single context can't be entered by two threads at once (Python raises
`RuntimeError`). No leaf tool emits events today, so nothing visibly breaks without it. A good way to check
that a test covers this: remove the copy, and the test should fail.

## Proxies can silently eat the feature

`Agent.act()` hands the whole turn to `execute_all()` when the tool set has it, and falls back to one
`execute()` per call when it doesn't, so a hand-written `ToolSet` keeps working. That fallback can hide a
problem. If `ToolboxView` (chapter 8) or a team member's tools (chapter 13) only had `execute()`, every call
behind them would run alone, with no error anywhere. `Harness(read_only=True)` uses a view, so it would
silently lose all concurrency.

This is D73's lesson again: anything that wraps an object has to keep up with its interface. Both proxies
answer their own calls (a hidden tool, `send_message`) and pass each *run* of the other calls on as one
batch, through a small shared helper. Runs, not "everything else at once": a team's `send_message` changes
the team's state, so it must happen between the calls around it.

## Testing concurrency without timing

Tests that sleep and compare clocks are slow and flaky. These tests use a `threading.Barrier` instead: a tool
that waits until N calls are inside it at once. If the calls really overlap, the barrier opens immediately.
If they run one at a time, the first call waits alone until the timeout, and the result is an error. So
"these ran concurrently" is a yes/no fact, not a measurement. Order tests work the same way: one call waits
on an `Event` that the other sets, which forces them to finish in reverse, and the test checks that outputs,
history and events still come out in the model's order.

A timing script shows the size of the win. Three tools that each sleep 0.3 seconds take about 0.9s with one
worker and 0.3s with three. Read, read, write, read takes about 0.9s instead of 1.2s: the two reads overlap,
then the write and the last read run alone.

## What to watch with a real model

Two questions only real runs answer: whether a model sends several read-only calls in one turn often enough
for this to matter, and whether a group's slowest call makes the console feel stuck (D218's cost).

## The one thing to remember

**Concurrency is cheap when calls are already objects and order is already explicit.** The hard part isn't
starting threads; it's everything that silently assumed one call at a time: the context a thread inherits,
the proxies in between, and the order observers see.

## Questions to think about

- Make a slow read-only tool and time a turn of three calls with one worker and with three. Then put a
  `write_file` in the middle and predict the time before you run it.
- Two reads on either side of a write don't merge, even when they touch different files (D215's cost). What
  would the Toolbox need to know to merge them safely, and who would have to tell it?
- List everything that would break if two sub-agents ran at once. Compare your list with D216.
