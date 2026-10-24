# Architecture decision log

Every non-obvious design choice, with the options and trade-offs, so the
reasoning survives longer than the conversation that produced it.
**Status:** `accepted` (chosen and built), `open` (revisit later),
`superseded by Dn` (replaced).

`PATTERNS.md` is your personal learning journal; this file records *what the
codebase decided and why*.

---

## Stage 2: Strategy + Adapter

### D1. Pin the wire format with characterization tests *before* refactoring
**Status:** accepted
- **Context:** the translation code was buried inside `call_llm`, with no tests.
  A refactor could silently change what reaches the API.
- **Options:** (a) refactor and check with live runs; (b) characterization tests
  with fake SDK clients first; (c) record/replay real HTTP traffic (VCR-style).
- **Chosen:** (b). Offline, free and exact. Live runs (a) are slow, cost money,
  and only check that *a* reply came back, not that the payload is identical.
  (c) is more faithful but heavier, so it's worth it later if fakes start to drift.
- **Lesson:** to refactor safely, first lock down the current behavior, warts included.

### D2. The provider interface is a `typing.Protocol` (your call)
**Status:** accepted
- **Options:** `Protocol` (structural) · `abc.ABC` (nominal) · plain callable.
- **Why:** test doubles and third-party classes qualify without inheriting from
  anything. **Cost:** a missing method only fails when it's called (or under a type
  checker), not at instantiation the way an ABC does.

### D3. Translation lives in separate adapter objects (your call)
**Status:** accepted
- **Options:** separate `to_wire`/`from_wire` adapters composed into providers ·
  private methods inside each provider.
- **Why:** it splits two reasons to change, the *format* (adapter) and the
  *transport/config* (provider). `OpenAIChatAdapter` can be reused for Ollama/vLLM
  with no subclassing. **Cost:** more files and one more hop when reading the code.

### D4. Agent receives a provider instance (your call)
**Status:** accepted
- **Options:** inject an instance · keep `provider="openrouter"` with a lookup table.
- **Why:** `Agent` depends only on the `Provider` protocol. **Cost:** callers must
  build providers themselves. `examples/hello.py` now has an `if/elif` on purpose:
  that's the smell stage 3 (Factory) fixes.

### D5. SDK clients are injectable: `Provider(model, client=None)`
**Status:** accepted (made during implementation)
- **Options:** (a) the provider always builds its own client; (b) `client` param
  with a real default; (c) client required, built by the caller or a factory.
- **Chosen:** (b). Tests pass a fake, and real use stays one line.
- **Trade-off:** the default hides a dependency on env vars (`OPENROUTER_API_KEY`).
  (c) is purer dependency injection, and stage 3's factory may move us there.

### D6. SDKs are imported lazily inside the provider constructors
**Status:** open (made during implementation)
- **Why:** importing `miniharness.providers` doesn't load both SDKs, so an
  Anthropic-only user wouldn't need `openai` installed.
- **Counterpoint:** both SDKs are required dependencies in `pyproject.toml`, so
  today this buys almost nothing and moves import errors to runtime.
- **Revisit when:** deciding whether the SDKs become optional extras
  (`uv add --optional anthropic ...`). If they don't, move the imports to the top.

### D7. Adapters build a *partial* request; providers add `model` and `max_tokens`
**Status:** accepted (made during implementation)
- **Why:** the model choice and the token budget are configuration, not format.
  Keeping them out of the adapter keeps it a pure function of (messages, tools).
- **Trade-off:** you need both classes to see the full request. Anthropic
  *requires* `max_tokens` and OpenAI doesn't, so the requirement lives with the
  provider, which knows its API.

### D8. Keep `Message.raw` for Anthropic's replayed content
**Status:** open (made during implementation)
- **Problem:** Claude's thinking blocks must be sent back unchanged, but the
  neutral `Message` type can't represent them.
- **Options:** (a) an opaque `raw` field (current); (b) `extras: dict[str, Any]`
  keyed by provider name; (c) providers keep their own native history, and
  the agent's history becomes a view of it.
- **Trade-off:** (a) is simple but leaky. If you switch providers mid-conversation,
  OpenRouter silently ignores `raw` while Anthropic would replay it. (c) is the
  cleanest but is a big redesign.
- **Revisit when:** stage 11 (Memento/checkpoints) forces us to decide what a
  serializable conversation actually contains.

### D9. Delete `call_llm` outright instead of keeping a compatibility shim
**Status:** accepted (made during implementation)
- **Why:** there are no external callers. A shim (`call_llm` delegating to providers)
  matters for a published library, where deprecation protects users. Here it
  would just be dead code.

### D10. Test fakes are duck-typed `SimpleNamespace` objects, not real SDK types
**Status:** accepted (made during implementation)
- **Why:** short, readable and independent of SDK internals. It works because the
  adapters only read attributes (structural typing again, as in D2).
- **Risk:** fakes can drift from the real response shapes after an SDK upgrade.
  Mitigation: the live smoke test (`examples/hello.py` on both providers).

### D11. `TOOLS` stays a global that `Agent` passes to providers
**Status:** superseded by D32 (stage 5)
- **Why defer:** it's out of scope for this refactor. Stage 5 (Command) redesigns
  tools, and the bonus stage replaces the global registry with dependency injection.

---

## Stage 3: Factory

### D12. Providers self-register with a decorator (your call)
**Status:** accepted
- **Options:** `@register_provider("name")` on each class · one explicit dict in
  one file · a `from_config()` Factory Method per class (still needs a lookup on top).
- **Why:** follows the Open/Closed principle. A new provider is one new class, and
  `create_provider` never changes. This is the core of the Factory idea: callers ask
  for *what* they want, and the registry knows *how* to build it.
- **Cost:** "magic at a distance". A provider only exists once its module is imported
  (see D16). An explicit dict is greppable and has no import side effects.

### D13. Providers are chosen with a `"provider:model"` spec string (your call)
**Status:** accepted
- **Options:** spec string · separate `name` + kwargs · TOML config profiles.
- **Why:** one value that works on the CLI, in env vars and in tests. It's also the
  convention in LangChain's `init_chat_model` and pydantic-ai.
- **Revisit when:** "Strategy part 2" (per-task model routing) needs named profiles.
  Config files can then *produce* spec strings, so the two don't conflict.

### D14. No Abstract Factory yet (your call)
**Status:** open (re-examined in stage 6, see D43)
- **Why:** an Abstract Factory builds *families* of objects that must match. Today a
  provider's only companion is its one fixed adapter, so a factory for families
  would be ceremony.
- **Trigger:** a second per-provider component that must pair correctly, e.g. stage
  6's pricing/token counting (OpenRouter returns cost; Anthropic needs a price table).

### D5 revisited: keep `client=None` (your call)
**Status:** accepted. `create_provider` stays a thin name-to-constructor mapping and
passes `client=` through as a kwarg, so tests still inject fakes.

### D15. Spec parsing splits on the *first* colon; no model means the provider's default
**Status:** accepted (made during implementation)
- **Why:** OpenRouter model ids can contain colons (`deepseek/deepseek-chat:free`).
  `str.partition(":")` handles that, and a test pins it.

### D16. Registration happens through `providers/__init__.py` importing every module
**Status:** accepted (made during implementation)
- **Risk:** add a provider module but forget the import, and the provider silently
  doesn't exist. `test_all_builtin_providers_are_registered` guards the built-ins.
- **Alternatives:** package entry points (`[project.entry-points]`, the plugin route
  that lets *other* packages add providers), or scanning the package with `pkgutil`.
  Both are more machinery than this project needs.

### D17. The registry is a module-level global
**Status:** open (made during implementation)
- **Smell:** it's a mutable singleton. Tests that register providers must
  `monkeypatch` it to avoid leaking state into other tests, the same pain the old
  `MOCK_RESPONSES` caused.
- **Alternative:** a `ProviderRegistry` instance passed where needed. That's purer, but
  then the decorator needs to know *which* registry to use.
- **Revisit when:** the bonus Singleton → dependency injection stage, which tackles
  this together with the `TOOLS` global (D11).

### D18. Registering a duplicate name raises instead of overwriting
**Status:** accepted (made during implementation)
- **Why:** fail loudly. A silent overwrite from a typo'd name or a double import
  would be very hard to debug.
- **Cost:** you can't deliberately replace a built-in provider (e.g. a patched
  OpenRouter) without adding an explicit `replace=True` option.

### D19. `create_provider` passes `**kwargs` through untyped
**Status:** accepted (made during implementation)
- **Why:** each provider has different constructor options (`max_tokens`, `client`, ...).
- **Cost:** no validation at the factory. A misspelled kwarg only fails as a
  `TypeError` from the constructor, and type checkers can't help.

### D20. `MockProvider(responses=None, model="mock")`: uniform construction
**Status:** accepted (made during implementation)
- **Why:** so `create_provider("mock")` works like any other provider.
- **Wart:** a mock built by the factory has no scripted responses, so
  `hello.py -m mock` fails on the first call. Mocks are meant for tests, which pass
  `responses=` directly.

---

## Stage 4: Builder

### D21. The Builder assembles the system prompt, not the Agent (your call)
**Status:** accepted
- **Options:** sectioned system-prompt builder · fluent `Agent.builder()` · skip the stage.
- **Why:** a Builder earns its place when construction has *rules*. Here the rule is
  real: stable sections first and volatile ones last, because prompt caching only reuses
  an unchanged prefix. A fluent Agent builder would duplicate what kwargs already do.

### D22. Mutable builder whose methods return `self` (your call)
**Status:** accepted
- **Options:** mutable `return self` · immutable copies (frozen dataclass + `replace`).
- **Cost:** a partially built builder can't be shared. Branching off it mutates the
  original, and `test_mutable_builder_is_shared_state` documents this. The director (D26)
  avoids the trap by returning a fresh builder each time.

### D23. Render order is fixed by the builder, not by the call order
**Status:** accepted (made during implementation)
- **Why:** callers can't accidentally put the date above the instructions. This is
  the Builder's real job: it owns the *assembly rules*, so callers only provide the parts.
- **Alternative:** render in call order and document "put volatile things last".
  That's a rule every caller has to remember.

### D24. `tool_rules()` takes guidance text, not the `TOOLS` dict
**Status:** accepted (made during implementation; differs from the preview)
- **Why:** providers already send tool schemas through the API's `tools` field.
  Repeating names and descriptions in the prompt costs tokens on every call and can
  drift out of sync with the real schemas.

### D25. `build()` returns a plain string
**Status:** open (made during implementation)
- **Alternative:** return structured blocks (stable part, volatile part) so the
  Anthropic adapter can put a `cache_control` breakpoint between them. That's the
  "same steps, different representations" side of Builder.
- **Revisit when:** stage 6 adds caching. Today no provider sets cache breakpoints, so
  the string is enough.

### D26. The Director is a function, `default_prompt()`, that returns a fresh builder
**Status:** accepted (made during implementation)
- **Why:** in GoF, a Director class holds a construction recipe. In Python, a function
  that returns a pre-filled builder is the same idea with less ceremony. Returning
  the *builder* (not the string) lets callers extend the recipe before `build()`.

### D27. Per-section semantics: identity replaces, rules append, environment merges
**Status:** accepted (made during implementation)
- `identity` is required, and `build()` raises without it. An agent with no identity
  is almost certainly a mistake. Empty sections are omitted entirely.
- Rendering uses markdown `## Heading` sections. XML tags (`<environment>`) would work
  equally well with Claude, and the choice lives in one place, so it's cheap to change.

### D28. Environment facts: coarse values and sorted keys
**Status:** accepted (made during implementation)
- The example passes the *date*, not a timestamp. That breaks the cached suffix once a
  day instead of on every request. Keys are sorted, so the same facts always render the
  same bytes, regardless of keyword order.
- **Behavior change:** `Agent`'s default prompt now comes from `default_prompt()`, which
  adds "prefer tools over mental arithmetic". It's a small change to what the model is
  told.

---

## Stage 5: Command

### D29. One class per tool, sharing a `Tool` base class (your call; base class mine)
**Status:** accepted
- **Options:** class per tool · `@tool` decorator that derives schemas from type hints.
- **Why:** classes give undo logic and per-tool state (a workspace root) a natural home.
- **Base class vs Protocol:** providers use a `Protocol` (D2), but tools use a base
  class because they share *defaults*: read-only, not reversible, and `undo()` raises.
  Inheritance carries defaults; a Protocol can't. The rule of thumb: Protocol for pure
  interfaces, a base class when there's shared behavior.

### D30. Tools declare `side_effects` and `reversible` (your call)
**Status:** accepted
- **Options:** declared reversibility · undo on everything (a no-op for read-only) ·
  no undo, only a log.
- **Why:** it's honest. A no-op `undo()` on "send email" would *look* like it worked.
  The two flags separate "changes nothing", "changes something reversibly" and
  "changes something permanently".

### D31. `read_file`/`write_file` confined to a workspace (your call)
**Status:** accepted
- `resolve_in_workspace` resolves `..` and symlinks *before* checking containment,
  so `../x`, absolute paths and symlinks pointing outside are all rejected (each is
  tested). Checking the raw string for `..` would miss symlinks.

### D32. The Agent receives an injected `Toolbox` (your call)
**Status:** accepted. This replaces the `TOOLS` global (D11). The Toolbox is the
*Invoker*: it looks tools up, runs each call as a `ToolCommand`, and keeps the history.

### D33. Undo by *snapshot*, not by *inverse operation*
**Status:** accepted (made during implementation)
- **Options:** (a) the tool records the prior state at run time (`_WriteUndo.previous`)
  and undo restores it; (b) the tool defines a compensating command (the inverse of
  "create file" is "delete file") without recording state.
- **Chosen:** (a). It's exact, and it's simple for files. (b) is what you need when
  state can't be snapshotted, like refunding a payment instead of "un-charging" it.
  That's the *Saga* pattern, common in distributed systems.
- **Note:** the snapshot is a small *Memento*, which previews stage 11.

### D34. `undo_last` stops at an irreversible side effect instead of skipping it
**Status:** accepted (made during implementation)
- **Why:** if a file was written and then emailed, undoing the write leaves the
  world inconsistent with what was sent. Stopping is the safe default, and a caller
  can still decide to skip deliberately.

### D35. Undo refuses if the file changed after our write
**Status:** accepted (made during implementation)
- This is *optimistic concurrency*: we remember what we wrote and only restore if
  the file still contains it. Otherwise undo would silently destroy someone else's edit.

### D36. Failed calls become error text for the model and stay out of the history
**Status:** accepted (made during implementation)
- **Why:** the model can recover from an error message. A failed call changed
  nothing, so there's nothing to undo. (`write_text` isn't atomic, so a crash halfway
  through a write is an accepted gap.)

### D37. The default toolbox is read-only; file tools need an explicit workspace
**Status:** accepted (made during implementation)
- This is the *principle of least privilege*: `Agent(provider)` with no arguments can't
  touch the disk. You have to grant filesystem access deliberately with
  `default_tools(workspace)`.

### D38. `read_file` truncates at 20,000 characters
**Status:** accepted (made during implementation)
- **Why:** one large file shouldn't flood the context window. The truncation note
  tells the model the file is longer. A smarter version would support line ranges.

### D39. Parallel tool calls run sequentially, in the order the model sent them
**Status:** open (observed live in this stage)
- The model sent `write_file` and `read_file` *in the same turn*. That worked only
  because we execute them in order. Running them concurrently would race.
- **Revisit when:** tools become async or slow. Options include running only
  read-only calls concurrently, or always respecting the order.

### D40. History is in memory, unbounded, and shared across runs of the same Toolbox
**Status:** open (made during implementation)
- `Agent.run()` doesn't reset `toolbox.history`, so a reused toolbox accumulates
  commands across tasks. That's handy for "undo the last task", but nothing marks
  where one run ends and the next begins.
- **Revisit when:** stage 11 (checkpoints) needs run boundaries and serializable history.

---

## Stage 6: Decorator

### D41. Four wrappers: usage tracking, budget guard, retry, dev cache (your call)
**Status:** accepted

### D42. Decorators are wrapper classes that are Providers themselves (your call)
**Status:** accepted
- **Options:** wrapper classes · a middleware list inside the Agent.
- **Why:** each wrapper is a `Provider`, so the Agent and the factory don't change.
  Wrappers stack, and the order is visible at the construction site.
- **Naming trap:** Python's `@decorator` syntax wraps *functions at definition time*.
  GoF Decorator wraps *objects at runtime*. These are different tools that share a name.

### D43. Each provider reports its own cost; still no Abstract Factory (your call)
**Status:** accepted
- OpenRouter returns `usage.cost` (USD) in every response, which we checked live before
  writing the code. The Anthropic API returns tokens only, so `AnthropicProvider.price()`
  multiplies by a small table.
- **D14 re-examined:** pricing is the second per-provider component, which was the
  stated trigger. But each provider still has exactly one adapter and one pricing rule,
  both fixed by its own constructor. There's no *family* to keep consistent, so an
  Abstract Factory would add a layer without preventing any mismatch. D14 stays open.

### D44. When the budget runs out, the Agent stops gracefully (your call)
**Status:** accepted. `run()` returns `"[stopped: budget] Spent $x of $y"`.

### D45. The Agent catches a `StopRun` base class, not `BudgetExceeded`
**Status:** accepted (made during implementation)
- **Why:** the Agent shouldn't know which wrappers exist. Any wrapper (budget, a future
  rate limit, a kill switch) can end the run cleanly by raising a `StopRun` subclass.
  The dependency points from wrappers to the Agent's contract, not the other way round.

### D46. Recommended stack: `DiskCache(Retry(BudgetGuard(UsageTracker(base))))`
**Status:** accepted (made during implementation)
- Order *is* behavior, and tests pin both cache placements:
  - cache outside the tracker: hits are free and don't count against the budget
  - cache inside the tracker: replayed responses count as spend again
  - retry outside the guard: every retry attempt is checked against the budget
  - tracker innermost: it sees every real call, including failed ones
- **Lesson:** decorators are composable, but they aren't *commutative*.

### D47. `BudgetGuard` wraps a `UsageTracker` specifically, not any Provider
**Status:** accepted (made during implementation)
- **Why:** the guard needs spend data, and the tracker owns it.
- **Alternatives:** the guard keeps its own running total (duplicate bookkeeping),
  or guard and tracker merge into one class (two responsibilities in one object).
- **Cost:** the guard can only sit directly on a tracker, a constraint the type signature
  makes explicit.

### D48. The budget fails closed when any cost is unknown
**Status:** accepted (made during implementation)
- **Why:** a budget you can't measure, you can't enforce. Treating unknown as $0 would
  let an unpriced model spend without limit.
- **Consequence:** an Anthropic model missing from the price table (D52) stops after
  its first call when a budget is set. That's loud on purpose.

### D49. `MalformedResponseError` carries usage, and the tracker records failed attempts
**Status:** accepted (made during implementation)
- **Why:** a malformed reply was still generated and billed. Without this, retries
  would be invisible spend.

### D50. `Retry` handles semantic failures only, with no backoff
**Status:** accepted (made during implementation)
- Both SDKs already retry 429s, 5xx errors and timeouts (2 retries by default). Adding
  network retries on top would multiply them: 3 of ours × 3 of theirs is up to 9 calls.
- Bad tool-call JSON isn't a rate problem, so an immediate retry is fine and no sleep is needed.

### D51. Cache key: namespace + model + tools + neutral messages; `raw` excluded; pickle storage
**Status:** accepted (made during implementation)
- **What's in the key:** anything that could change the answer. **What's left out:**
  `raw`, which is provider-specific and derived from the rest. If it were included, the
  same conversation could hash differently.
- **Observed limit:** tool *outputs* are part of the conversation. After a `current_time`
  call the conversation differs every run, so the cache only helps up to the first
  non-deterministic tool call.
- `pickle` can store Anthropic's SDK objects, but loading a pickle can run code, so it's
  only safe for a cache directory you control. Errors aren't cached.
- **Not the same as prompt caching:** this cache skips the API entirely, on our side.
  Provider-side prompt caching (D25, still open) makes repeated prefixes cheaper, but
  the call still happens.

### D52. Anthropic prices are a hardcoded, simplified table
**Status:** open (made during implementation)
- It ignores prompt-cache pricing and Haiku's higher rate above 100K input tokens.
  Hardcoded prices go stale. The real fix would be a pricing source with a date,
  or the provider's own usage reporting.

### D53. A provider that reports no usage counts as unknown cost
**Status:** accepted (made during implementation)
- `UsageTracker` records `Usage()` (cost `None`) when a response has no usage. With a
  budget, that fails closed (D48). Mock responses in tests must therefore include usage
  when a budget is involved.

### D54. The example composes the stack by hand instead of using a helper
**Status:** accepted (made during implementation)
- **Why:** the order matters (D46) and should be visible where it's built.
- **Revisit when:** the same stack is built in more than one place. A helper
  would then be a small Director, like `default_prompt()` in stage 4.
