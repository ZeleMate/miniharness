# Chapter 16. One front door

*Pattern: [Facade](https://refactoring.guru/design-patterns/facade). Code: `src/miniharness/harness.py`, `src/miniharness/providers/stack.py`.*

## Ten objects in the right order

By stage 15, a capable agent meant hand-composing about ten objects, in the right order: a provider inside
five wrapper layers (in chapter 6's order), a Toolbox with a policy chain and an approver, one event bus
passed to *both* the agent and the toolbox (forget one and tool events silently disappeared), observers, a
prompt from the Builder, an autosave observer and sub-agents. `examples/hello.py` had grown to 165 lines,
mostly wiring, and every new script copied it.

A Facade offers one simple entry point to a complicated subsystem.

## The Harness

You chose a `Harness` class that owns its subsystems and exposes them (D173), configured with flat keyword
arguments that all have safe defaults (D174):

```python
h = Harness("openrouter", budget=0.05, workspace="ws", approve=True)
print(h.run("Write a haiku to haiku.txt"))
print(h.report())
```

After construction it offers a narrow API: `run()`, `follow_up()`, `stream()`, `resume()`, `add_helper()`,
`rewind()` and `report()`. `examples/hello.py` shrank from 165 lines to 95, almost all of which is now
argument parsing (D186).

## A facade simplifies; it doesn't lock anything away

The most important design principle of this stage: everything the facade built stays a public attribute.
`h.agent`, `h.toolbox`, `h.stack.tracker` and `h.events` are all reachable. A factory function that
returned only an `Agent` would have buried the tracker, the cache and the fallback chain inside the
wrapper stack (`agent.provider.inner.inner...`). With the Harness, the advanced case starts from a working
setup instead of a blank file. GoF says the same: clients may always bypass a facade. The streaming example
still wires an `Agent` by hand on purpose, so someone keeps showing the parts.

## The recipe moves to one place

Chapter 6 had kept the wrapper stack hand-built, so its order stayed visible, with a note: "add a helper
once it's built in more than one place" (D54). The facade and the team example were those places, so the
recipe became a public `build_stack()` function (D175). Like `default_prompt()` from chapter 4, it's a
*Director*: a function that knows the order. It returns a `Stack` holding handles to the layers callers
read afterwards (the tracker for cost, the cache for hits, the fallback chain for failures), so nobody
walks `.inner` to find them.

## Defaults are the facade's real design work

The parts can do anything, so the facade's job is deciding what happens when the caller says nothing. Every
default here points the same way (D176):

- **Side effects are denied unless `approve=` is given.** A library should never call `input()` on its own,
  because that hangs headless runs in CI, on a server or in a subprocess. Live, with all defaults, the model
  tried to write a file, was told it needed approval, and explained this to the user.
- **Every run has a $0.05 budget**, unless you pass `budget=None`.
- **File tools exist only when a workspace is given.**

The facade also wires one event bus through the agent, the toolbox and every helper (D177), which fixed
chapter 10's lost-events problem for this path. A few other choices are worth noting: the console printer is
on by default, which is unusual for a library but right for a learning harness (D180); the facade doesn't
load `.env`, because loading environment files is the application's job (D181); and `add_helper()` only
makes read-only sub-agents, since a writing helper raises questions (whose approval? whose undo history?)
the facade shouldn't answer silently (D184).

## When defaults combine

The parts had been tested separately; the facade combined them, and the combinations behaved in new ways.

**Breaking out of a stream blocks the next call (D179).** Chapter 15 made an abandoned stream's cost
unknown. Chapter 6 made the budget fail closed on unknown cost. Separately, both were right. But now every
Harness has a budget *by default*, so any `break` out of `h.stream()` followed by another call stops with
`[stopped: budget]`. That was confirmed live, and it's still open.

**An old bug surfaced while moving code (D182).** The checkpoint autosave in the old example reacted to
*every* agent's events. With a helper sub-agent and checkpoints, the helper finishing deleted the main run's
checkpoint mid-run. Moving the code into the facade, where it had to be written carefully, exposed it. The
facade's autosave now ignores sub-agent events, and `run()` never silently resumes an old run; `resume()`
does that explicitly.

**A `.env` gotcha.** `load_dotenv()` with no arguments searches from the calling *script's* folder, not the
current directory. A script outside the repo found no key. It's a small thing, and it's exactly the kind of
thing only a live run finds.

## Facade vs its neighbours

- **Facade vs Mediator:** both sit in front of a group of objects. A Mediator sits *between* peers that talk
  through it, and the peers know it. A Facade sits *in front of* a subsystem for an outside client, and the
  subsystem doesn't know it exists. Nothing in the agent, toolbox or wrappers changed this stage.
- **Facade vs Builder (D185):** a Builder assembles one product under rules and is done. A Facade is still
  there afterwards, as the simple way to *use* many objects. Here they cooperate: the facade calls two
  Directors.

## The one thing to remember

**A facade's real design work is its defaults.** It should make the common case one line, keep every part
reachable, and choose what happens when the caller says nothing, preferably the safe thing.

## Questions to think about

- Write a 20-line script that uses a Harness with a read-only helper to review a file. Which part did you
  have to reach past the facade for?
- D179 shows two correct defaults combining badly. Where might that happen in tools you've built?
