# Chapter 8. Stand-ins

*Pattern: Proxy. Code: `src/miniharness/providers/proxies.py`, `src/miniharness/tools/view.py`.*

## Same shape, different intent

A Proxy looks exactly like a Decorator: an object that wraps another object and has the same interface.
The difference is entirely **intent**:

- A **Decorator** *adds behavior*: the tracker counts, the cache replays.
- A **Proxy** *controls access* to the real object: whether you reach it, when, or where it actually runs.

GoF names three classic kinds. A **virtual** proxy creates the expensive object only when it's first
needed. A **protection** proxy checks rights before access. A **remote** proxy is a local stand-in for
something running elsewhere. This stage asked where each would solve a problem the project actually had.

## The virtual proxy: a provider that isn't built yet

The real problem: building an `OpenRouterProvider` required the API key *at construction*, and `--fallback`
built both SDK clients up front, even though the backup might never be used. A missing backup key would
crash a run that didn't need the backup at all.

`LazyProvider` defers construction until the first call:

```python
backup = lazy_provider("anthropic:claude-haiku-5-5")   # no key, no client, nothing built
FallbackChain([main, backup])                          # backup built only if main fails
```

A `materialize()` method lets callers fail fast on purpose (D69): the example builds the *main* provider
eagerly, so a broken config fails at startup, but keeps the fallback lazy. The proxy can answer some
questions without building anything (its model name, if the spec includes one) and must build the real
thing for others (D71). That split between what the stand-in knows and what needs the real object is
typical of proxies.

This also settled an older decision. Chapter 2 had made SDK imports lazy inside constructors (D6), which
bought almost nothing. Now the laziness that matters lives in one explicit object, and the imports moved
back to the top of each module (D70).

## The protection proxy: tools the model can't see

`ToolboxView` exposes only some of a Toolbox's tools:

```python
reader_tools = ToolboxView.read_only(toolbox)   # add, multiply, current_time, read_file
```

Hidden tools don't appear in the tool list sent to the model, and calling one returns exactly the same
error as a tool that doesn't exist (D74). A "permission denied" message would confirm the tool exists, so
this is information hiding, a common security stance. Allowed calls still go through the real Toolbox, so
its policy chain and history still apply (D75). That's defense in depth: the view hides tools *before* the
model can try them, and the chain decides *after* it tries.

To accept a view, the Agent had to stop depending on `Toolbox` itself. It now depends on a tiny `ToolSet`
protocol with two methods, `specs()` and `execute()` (D76). That's the *interface segregation principle*:
the Agent uses two methods, so it asks for exactly two, and any object with them can stand in.

## The live lesson: hiding beats refusing

With a read-only view, the model asked to write a file never even tried. It couldn't see `write_file`, so
it read the folder and explained it couldn't write files. No denial was needed, because the option didn't
exist. **Hiding a capability is stronger than refusing it**, since a refusal still invites the model to
argue, retry or route around it.

## Re-reading chapter 6

With the distinction sharp, chapter 6's `BudgetGuard` turned out to be misfiled (D72). It never changes a
response; it only decides whether the call happens. That's a protection proxy, not a decorator. The code
didn't move. Classifying by intent doesn't require reorganizing files, but the recommended stack now reads
as a mix of both kinds: decorators that add behavior and one proxy that guards access.

## A smell introduced

The dev cache derives a namespace from the innermost provider by unwrapping wrappers one by one. Wrapping a
`LazyProvider` meant that unwrapping *built* it, defeating the point. The fix was to resolve the namespace
on first use and teach the unwrapping code about proxies (D73). But that's a smell worth noticing: proxies
are meant to be transparent, and any code that *introspects* wrappers breaks that transparency. The remote
proxy was skipped (D68): it's the idea behind MCP servers and sandboxed execution, but nothing here needed
process isolation yet.

## The one thing to remember

**Ask whether a wrapper changes *what happens* or *whether it can happen*.** The first is a Decorator, the
second a Proxy. Identical code, different jobs, and the difference tells you where it belongs in a stack.

## Questions to think about

- A wrapper that logs every tool call: Proxy or Decorator? One that requires approval: which, and what
  changed?
- Where in your systems would hiding a capability be safer than refusing it at runtime?
