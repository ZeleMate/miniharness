# Chapter 16. One front door

*Pattern: [Facade](https://refactoring.guru/design-patterns/facade). Code: `src/miniharness/harness.py`, `src/miniharness/providers/stack.py`.*

## Ten objects in the right order

By stage 15, a capable agent means hand-composing about ten objects, in the right order: a provider inside
five wrapper layers (in chapter 6's order), a Toolbox with a policy chain and an approver, one event bus
passed to *both* the agent and the toolbox (forget one and tool events silently disappear), observers, a
prompt from the Builder, an autosave observer and sub-agents. Every script that wants a capable agent copies
that wiring.

A Facade offers one simple entry point to a complicated subsystem.

## The Harness

`Harness` is a class that owns its subsystems and exposes them (D173), configured with flat keyword
arguments that all have safe defaults (D174):

```python
h = Harness("openrouter", budget=0.05, workspace="ws", approve=True)
print(h.run("Write a haiku to haiku.txt"))
print(h.report())
```

After construction it offers a narrow API: `run()`, `follow_up()`, `stream()`, `resume()`, `add_helper()`,
`rewind()` and `report()`. With it, almost all of `examples/hello.py` is argument parsing (D186).

## A facade simplifies; it doesn't lock anything away

The most important design principle of this stage: everything the facade builds stays a public attribute.
`h.agent`, `h.toolbox`, `h.stack.tracker` and `h.events` are all reachable. A factory function that
returned only an `Agent` would bury the tracker, the cache and the fallback chain inside the wrapper stack
(`agent.provider.inner.inner...`). With the Harness, the advanced case starts from a working setup instead
of a blank file. GoF says the same: clients may always bypass a facade. The streaming example still wires an
`Agent` by hand on purpose, so the parts stay visible somewhere.

## The recipe moves to one place

Chapter 6 keeps the wrapper stack hand-built, so its order stays visible, with a trigger: "add a helper once
it's built in more than one place" (D54). The facade and the team example are those places, so the recipe
becomes a public `build_stack()` function (D175). Like `default_prompt()` from chapter 4, it's a
*Director*: a function that knows the order. It returns a `Stack` holding handles to the layers callers read
afterwards (the tracker for cost, the cache for hits, the fallback chain for failures), so nobody walks
`.inner` to find them.

## Defaults are the facade's real design work

The parts can do anything, so the facade's job is deciding what happens when the caller says nothing. Every
default here points the same way (D176):

- **Side effects are denied unless `approve=` is given.** A library should never call `input()` on its own,
  because that hangs headless runs in CI, on a server or in a subprocess. With all defaults, a `write_file`
  call is told it needs approval, and the model can only report that.
- **Every Harness has a $0.05 budget**, shared by all its runs, unless you pass `budget=None`.
- **File tools exist only when a workspace is given.**

The facade also wires one event bus through the agent, the toolbox and every helper (D177), which fixes
chapter 10's lost-events problem for this path. Other defaults: the console printer is on, which is unusual
for a library but right for a learning harness (D180); the facade doesn't load `.env`, because loading
environment files is the application's job (D181); and `add_helper()` only makes read-only sub-agents, since
a writing helper raises questions (whose approval? whose undo history?) the facade shouldn't answer silently
(D184).

## When defaults combine

Parts tested separately can behave in new ways once a facade combines them.

**Breaking out of a stream blocks the next call (D179).** Chapter 15 makes an abandoned stream's cost
unknown. Chapter 6 makes the budget fail closed on unknown cost. Separately, both are right. But every
Harness has a budget *by default*, so any `break` out of `h.stream()` followed by another call stops with
`[stopped: budget]`. It's tested, and it's open.

**Autosave must ignore sub-agents (D182).** A checkpoint autosave that reacts to *every* agent's events
breaks with helpers: a helper finishing deletes the main run's checkpoint mid-run. The facade's autosave
ignores events from sub-agents, and `run()` never silently resumes an old run; `resume()` does that
explicitly.

**A `.env` gotcha.** `load_dotenv()` with no arguments searches from the calling *script's* folder, not the
current directory, so a script outside the repo finds no key. Pass the path explicitly.

## Facade vs its neighbours

- **Facade vs Mediator:** both sit in front of a group of objects. A Mediator sits *between* peers that talk
  through it, and the peers know it. A Facade sits *in front of* a subsystem for an outside client, and the
  subsystem doesn't know it exists. Nothing in the agent, toolbox or wrappers changes for the facade.
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
