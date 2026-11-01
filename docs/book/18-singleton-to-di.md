# Chapter 18. The last global

*Pattern: [Singleton](https://refactoring.guru/design-patterns/singleton), and why dependency injection replaces it. Code: `src/miniharness/providers/registry.py`,
`tests/test_singleton.py`.*

## A pattern you learn in order to avoid

Singleton is the GoF pattern best learned *in order to avoid*. It guarantees one instance of a class,
reachable from anywhere. That sounds convenient, and the costs only show up later, mostly in tests.

The build has met those costs three times already. Chapter 2 removes `MOCK_RESPONSES`, a global list tests
have to clear. Chapter 5 removes the global `TOOLS` dict. And chapter 3 introduces the provider registry, a
module-level dict that `@register_provider` fills at import time and `create_provider` reads (D17). A test
that registers a throwaway provider has to monkeypatch the module to stop it leaking into every later test.
That's the last piece of hidden global state.

## Naming the pattern without shipping it

"Naive first" usually means building the smelly version before fixing it. But this smell is already
present, so shipping a Singleton only to remove it in the next commit would be ceremony. The middle path
(D202): the textbook Singleton lives in a *test file*, as a runnable specimen, with the same scenarios
written the dependency-injection way right below it.

The specimen makes every cost concrete: there's one instance; a "fresh" object isn't fresh, because it
carries everyone's earlier changes; state leaks from one test into the next; every test needs a reset
fixture; and nothing in any function signature says it depends on the registry. It also shows a
Python-specific trap: `__init__` still runs on every `SingletonRegistry()` call, so a Singleton's `__init__`
must not initialize anything, or it wipes the shared state every time.

## The refactor

The registry becomes an ordinary class, and the built-ins register into one ordinary instance (D203):

```python
mine = default_registry.copy()


@mine.register("echo")
class EchoProvider(MockProvider): ...


Harness("echo", registry=mine)  # the default registry is untouched
```

`create_provider()` and `@register_provider` still exist, as one-line delegates to `default_registry`, so
no existing caller changes. Everything that turns a spec into a provider (`build_stack`, `lazy_provider`,
`Harness`) accepts `registry=`. The payoff is concrete: every test that monkeypatched the registry now
builds or copies its own, and no monkeypatching of it is left in the test suite.

## What actually changed

`default_registry` is still a module-level, mutable object. So what changed? **The direction of the
dependency.** Before, every caller *reached out* for the global and couldn't be handed anything else. Now
the global is just the default argument, and every constructor that needs a registry says so in its
signature. A Singleton is "one instance, globally reachable, enforced". This is "one instance by convention,
passed in when it matters".

Two alternatives lose. Removing the global entirely would reverse the convenient self-registration from
chapter 3 for purity no caller needs. And an ambient ContextVar (`with use_registry(r):`) would hide the
dependency again, just scoped.

## Why the other module-level object stays

That raises a fair question: chapter 12 puts a ContextVar at module level to track which agent is running.
Isn't that a singleton too? No, and the difference is a useful rule (D210):

- **Inject what an object needs to do its job:** a registry, a provider, a bus, tools. That's configuration
  someone might want to swap.
- **Use a ContextVar for facts about the current call stack:** which agent is running, how deep, a request
  id, a trace span. Each thread and asyncio task sees its own value, a `with` block resets it, and there's
  nothing anyone would configure from outside. Python's `logging`, OpenTelemetry's current span and
  `decimal`'s context all work this way.

## "Whoever creates an object wires it"

The same rule settles chapter 10's oldest open problem (D204). `Agent(provider)` with no tools builds its
default Toolbox *itself*, so it gives that Toolbox its own event bus. Without that, tool events are silently
lost on exactly the shortest path. A Toolbox you pass in is yours to wire: the Agent doesn't reach into
objects it was only handed. A plain `Agent` reports its tool calls with no manual wiring.

Smaller decisions: `registry=None` means the default, resolved inside the function, which is Python's
convention for mutable defaults (D205); `copy()` makes an independent snapshot, not a parent chain that
would leak later changes (D207); any callable can be a factory, so registering an alias is three lines
(D208); and duplicates still raise, because deliberate replacement is now just "use a different registry"
(D209).

## Where Python dissolves the pattern

In Python, **a module is a singleton**: it's imported once and cached in `sys.modules`. So the Pythonic
"Singleton" is simply a module-level object, which is exactly what `_REGISTRY` is. That's why the
`__new__`-based class form is rare in Python code, and why removing the pattern here means changing who
*reaches for* the object, not deleting a class.

## The one thing to remember

**The problem with a Singleton isn't that there's one instance; it's that callers reach for it instead of
being given it.** Keep one default instance if it's convenient, and let every consumer accept another.

## Questions to think about

- Run two Harness objects side by side, each with its own registry where "main" means a different provider.
  Could they coexist with only the global registry?
- Find a place in your own agent code that reaches for a global client or config. Who should create it and
  pass it in?
