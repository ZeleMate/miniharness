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
**Status:** superseded by D70 (stage 8)
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
**Status:** open; serialization settled by D106 (stage 11), the leak itself remains
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

---

## Stage 7: Chain of Responsibility

### D55. Two chains: tool-call policy and model fallback (your call)
**Status:** accepted
- **CoR vs Decorator (stage 6):** a decorator *always* passes the call on and adds
  behavior along the way. In a chain, each link may *handle* the request and stop it.
  The question a chain answers is "who deals with this?", not "what else happens?".

### D56. A policy chain is a list where the first verdict wins (your call)
**Status:** accepted
- **Options:** a list of `check() -> Decision | None` · GoF linked handlers with `next`.
- **Why:** policies don't know about each other, reordering means editing a list, and
  forgetting to call `next` (a classic bug in the linked form) can't happen. It's the
  same intent with a different structure.

### D57. `ASK` is a verdict, resolved by the chain's injected approver
**Status:** accepted (made during implementation; refines your approval choice)
- **Why:** it separates *deciding to ask* (a policy) from *how to ask* (terminal, Slack,
  web UI). The policies stay pure, and the approver is swappable and easy to test.
- With no approver, `ASK` becomes `DENY`, so unattended runs fail closed.

### D58. When no policy decides, deny (your call)
**Status:** accepted. This is consistent with D37 (read-only default toolbox) and D48
(fail-closed budget).
- **Behavior change:** `Toolbox(default_tools(workspace))` with no policy can no
  longer write files. It now needs an approver or an explicit policy. The execution
  tests use `PolicyChain.allow_all()`, so their intent is visible.

### D59. Approver is an injected callback; a denial is returned to the model as text (your call)
**Status:** accepted
- Observed live: after a declined `write_file`, the model explained that it lacked
  permission and asked the user how to proceed. The run degraded gracefully.

### D60. Policy is checked in `Toolbox.execute`, before the command is created
**Status:** accepted (made during implementation)
- **Why:** the invoker is the single gate every call passes through. Denied calls
  never become commands, so they're kept apart in `toolbox.denied` and aren't in
  the undo history.

### D61. Every `Decision` names its reason and the policy that made it
**Status:** accepted (made during implementation)
- **Why:** "why was this allowed?" is the first question when a permission system
  surprises you. The example prints `denied write_file: ... (by AskBeforeSideEffects)`.

### D62. `MaxCalls` is a quota, not a rate limit
**Status:** accepted (made during implementation; renamed from the preview's `RateLimit`)
- It counts calls over the chain's lifetime, with no time window. Naming it honestly
  avoids implying behavior it doesn't have.
- A call is counted when it passes `MaxCalls`, even if a later policy denies it.

### D63. Fallback only on *transient* errors, never on configuration errors
**Status:** accepted (found in a live run)
- **What happened:** the first version fell back on any SDK `APIError`. A live run
  with an invalid Anthropic key got `401 invalid x-api-key`, and the chain quietly
  answered with DeepSeek. That hid a broken key and spent money on another model.
- **Now:** fall back on connection errors, timeouts, rate limits, 5xx errors and
  malformed replies. Auth, permission, bad-request and not-found errors propagate.
- **Lesson:** decide which failures mean "try someone else" and which mean "you
  have a bug". A fallback that catches everything is a bug-hider.

### D64. Fallback on refusal; the last link's refusal is returned, not raised
**Status:** accepted (made during implementation)
- A refusal is an answer, not an error, so if no one else can help, the caller sees it
  as a normal `stop_reason="refusal"`.

### D65. No circuit breaker: every call tries the failing provider first again
**Status:** superseded by D79 (stage 9)
- In the fallback run, each of the agent's two model calls hit the broken provider
  before falling back, which costs latency and money on every turn.
- **Revisit when:** stage 9 (State). A circuit breaker (closed → open → half-open) is a
  textbook State machine: after N failures, skip the provider for a cooldown period.

### D66. Usage of a refusal swallowed by the fallback is invisible to an outer tracker
**Status:** open (made during implementation)
- With `UsageTracker(FallbackChain([...]))`, the tracker only sees the response that
  was returned. A refused response was still billed, but nobody counts it.
- **Fix options:** a tracker inside each link, or the chain reporting swallowed usage.

### D67. After a fallback, one conversation mixes providers
**Status:** open (made during implementation)
- Turn 1 may come from Anthropic (with `raw`) and turn 2 from OpenRouter (without it).
  Both adapters tolerate this today, but it's the D8 leak in action: the conversation
  type doesn't record which provider produced which turn.

---

## Stage 8: Proxy

### D68. Three proxies: virtual (lazy provider), protection (toolbox view), and BudgetGuard reclassified (your call)
**Status:** accepted
- **Proxy vs Decorator:** same structure (a wrapper with the same interface), different
  intent. A decorator *adds behavior*. A proxy *controls access to the real object*:
  whether you reach it, when, or where it runs.
- **Skipped:** the remote proxy (running a tool in a subprocess). It's the idea behind MCP
  servers and sandboxed execution, but it's the most code of the three, and nothing in the
  project needs process isolation yet.

### D69. A lazy provider fails at first use, with `materialize()` to fail fast on purpose (your call)
**Status:** accepted
- The example builds the main provider eagerly with `create_provider`, the same as
  materializing at startup, and keeps only the fallback lazy. A broken *main* config fails
  at startup, and a missing *backup* key only matters if the backup is ever needed.

### D70. SDK imports move to the top of each module; the lazy proxy owns laziness
**Status:** accepted (supersedes D6)
- **Why:** D6 made constructors import SDKs lazily, which bought almost nothing because
  both SDKs are required dependencies. Laziness that matters (no key and no client until
  needed) now lives in one explicit object instead of being scattered across constructors.

### D71. `LazyProvider.model` answers without building when the spec names a model
**Status:** accepted (made during implementation)
- `lazy_provider("openrouter:qwen/...")` knows its model from the spec. With no model
  in the spec, the default lives in the provider's constructor (env var), so asking for
  `.model` has to build it. Proxies often face this: some questions can be answered by the
  stand-in, and others need the real thing.

### D72. `BudgetGuard` is a protection proxy, not a decorator (your call; docs only)
**Status:** accepted
- It never changes a response; it only decides whether the call happens. The D46
  stack therefore mixes both kinds: `UsageTracker`, `Retry` and `DiskCache` add behavior,
  while `BudgetGuard` controls access. The code stays in `wrappers.py`, and the docstring
  says what it really is. A classification by intent doesn't need to move code.

### D73. Code that unwraps wrappers must also see through proxies
**Status:** open (made during implementation)
- `DiskCache` derives its namespace from the innermost provider. Wrapping a `LazyProvider`
  meant unwrapping it, which builds it. The namespace is now resolved on first use, and
  `_innermost` materializes lazy proxies.
- **Smell:** `isinstance`-based unwrapping has to know every wrapper and proxy type.
  Proxies are meant to be transparent, and introspection breaks that. An alternative is
  a small `inner_provider()` method on every wrapper and proxy.

### D74. Hidden tools look exactly like missing tools
**Status:** accepted (made during implementation)
- Calling a tool the view hides returns `Error: unknown tool 'write_file'`, the same as
  a tool that doesn't exist. A "permission denied" message would confirm the tool exists.
  This is information hiding, a common security stance.

### D75. A view shares the real Toolbox's policy and history; undo stays on the Toolbox
**Status:** accepted (made during implementation)
- The view only narrows *what can be called*. Allowed calls still pass the policy chain,
  which gives defense in depth: the view hides tools *before* the model can try them, and
  the chain decides *after* it tries.
- No `undo_last` on the view: undoing through a view would undo the shared Toolbox's
  last change, which might not be one the view made.

### D76. The Agent depends on a `ToolSet` protocol (`specs()` + `execute()`), not on `Toolbox`
**Status:** accepted (made during implementation)
- This is the *interface segregation principle*: the Agent uses two methods, so it asks
  for exactly those two. That's what lets a `ToolboxView`, or a future remote tool set,
  stand in for a Toolbox.

### D77. Views take an allow list, checked at construction
**Status:** accepted (made during implementation)
- An allow list is least privilege: new tools added to the Toolbox stay hidden from
  existing views. A typo in the list (`"writefile"`) raises immediately instead of
  silently hiding a tool.

### D78. `LazyProvider` is not thread-safe
**Status:** accepted (made during implementation)
- Two threads calling it at the same moment could both build the real provider.
  Nothing in the harness is concurrent today. A lock fixes it if that changes (D39).

---

## Stage 9: State

### D79. Two state machines: a circuit breaker and the agent lifecycle (your call)
**Status:** accepted
- **Breaker:** fixes D65. Observed live, an unreachable primary was tried once, the
  breaker opened, and the next two turns skipped it instantly with no network call.
- **Lifecycle:** partly speculative, since `run()` worked fine as a loop. It earns its keep
  in stage 10 (each transition is a natural event to observe) and stage 11 (state boundaries
  are safe points to checkpoint and resume).

### D80. One class per state, GoF style (your call)
**Status:** accepted
- **Options:** state classes · an Enum plus a transition table.
- **Why:** each state's behavior lives in one place, and no method branches on "which
  state am I in?". A transition is assigning a new state object.
- **Cost:** more classes. For a two-state toggle, an Enum is simpler. The pattern pays off
  when states *behave* differently, as the breaker's three do.

### D81. An open breaker raises `CircuitOpenError`, which counts as transient (your call)
**Status:** accepted
- `FallbackChain`'s default errors include it, so an open breaker means "skip me".

### D82. Only transient errors trip the breaker
**Status:** accepted (made during implementation)
- A bad key or an unknown model passes straight through without counting, which is
  consistent with D63. Waiting won't fix a configuration bug, so opening the circuit
  would only delay the real error.

### D83. The failure count is state-local data owned by `Closed`
**Status:** accepted (made during implementation)
- **Why:** entering `Closed` creates a fresh object, so the count resets automatically.
  No "remember to reset the counter" code exists anywhere. State objects can carry the
  data that only matters in that state, like `Open.opened_at` and `ActingOnTools.calls`.
- **Trigger:** N *consecutive* failures, not a failure rate over a time window. Rates
  are more robust under steady traffic, but an agent makes few calls.

### D84. The breaker takes an injected clock, defaulting to `time.monotonic`
**Status:** accepted (made during implementation)
- Tests drive time with a fake clock instead of sleeping. A monotonic clock is immune to
  wall-clock changes (NTP, daylight saving), so cooldowns can't jump.

### D85. The circuit breaker is a protection proxy whose behavior is a state machine
**Status:** accepted (made during implementation)
- Patterns compose: by *intent* it's a proxy (it controls whether the provider is reached),
  and by *implementation* it's State. It subclasses the wrapper base, so unwrapping (D73)
  and `.model` work.

### D86. `Open` → `HalfOpen` happens lazily, on the next call after the cooldown
**Status:** accepted (made during implementation)
- There's no timer thread. The cost is that `breaker.state` still reads "open" after the
  cooldown until something calls it. A passive transition is simpler, and nobody
  watches the state between calls.

### D87. `HalfOpen` lets one trial through; not thread-safe
**Status:** accepted (made during implementation)
- With concurrent callers, all of them could pass in half-open. It's fine while the harness
  is sequential (D39, D78).

### D88. A refusal counts as success for the breaker
**Status:** accepted (made during implementation)
- A provider that refuses is healthy, just unwilling. Whether to try another provider is the
  fallback's decision (D64), not the breaker's.

### D89. Lifecycle states call the Agent's Template Method hooks
**Status:** accepted (made during implementation)
- `Thinking.step()` calls `agent.think()` and `agent.finish()`, so subclasses that override a
  hook keep working (tested with `Shouty`). State decides *when* a step happens; Template
  Method decides *how* it's done.

### D90. Exceeding `max_steps` still raises `RuntimeError`
**Status:** open (made during implementation)
- A `Stopped("max_steps")` state would be more consistent with budget stops, but it changes
  what callers see (a returned string instead of an exception). The refactor kept behavior
  identical, and all 106 earlier tests passed unchanged.

### D91. No `AwaitingHuman` state: approval stays synchronous inside the Toolbox
**Status:** open, now unblocked: stage 11 can persist a paused run (D118)
- The approver blocks inside `Toolbox.execute()`. A real `AwaitingHuman` state would mean
  *pausing* the run, returning control, and resuming when someone answers, possibly hours
  later or in another process.
- **Revisit when:** stage 11 (Memento) can persist a paused run. That's the
  missing piece for asynchronous approval.

### D92. `start()` works from `Idle` or a finished state; it refuses while running
**Status:** accepted (made during implementation)
- Restarting resets messages and the model-call count. The Toolbox history is *not* reset (D40).

---

## Stage 10: Observer

### D93. Typed, frozen event dataclasses delivered through an `EventBus` (your call)
**Status:** accepted
- **Options:** typed events plus a bus · an observer base class with `on_*` hook methods.
- **Why:** adding an event type never changes an interface, so existing observers keep
  working. Subscribers pick events with `match`.
- **Cost:** less discoverable than hook methods. You read `events.py` to see what exists.

### D94. One shared bus, injected into the Agent and the Toolbox (your call)
**Status:** accepted
- Only the Toolbox knows a call's policy decision, so it emits `ToolCalled(decision=...)`.
  The Agent emits run, state and model events. With one bus, one subscriber sees the
  whole story in order.

### D95. A failing observer is isolated, recorded and warned about (your call)
**Status:** accepted
- A broken observer can't change the run's outcome (tested with a handler that
  divides by zero). This keeps the defining property of Observer: subjects don't depend
  on their observers.

### D96. Two observers: `ConsolePrinter` and `JsonlTracer` (your call)
**Status:** accepted. The example now shows progress live instead of reconstructing it
from `agent.messages` afterwards.

### D97. Events are emitted from framework code, not from overridable hooks
**Status:** accepted (made during implementation)
- `StateChanged` comes from `Agent._transition` and `ModelCalled` from `Thinking.step`,
  not from `think()`. A subclass that overrides `think()` still produces events (tested).
  If the emit lived inside the hook, every override would have to remember `super()`.

### D98. The Agent always has a bus; it doesn't share it with the Toolbox automatically
**Status:** open (made during implementation)
- `Agent(..., events=None)` creates an empty bus, so `agent.events.subscribe(...)` always
  works. The Toolbox's bus is optional, and the caller must pass the same one to both.
- **Risk:** forget to pass it to the Toolbox, and `ToolCalled` events silently never arrive.
  Auto-wiring (the Agent handing its bus to its tools) would fix that, at the cost of the
  Agent reaching into a component it otherwise treats as a black box (D76).

### D99. Delivery is synchronous, in the emitting thread
**Status:** accepted (made during implementation)
- Simple, ordered and deterministic in tests. The cost is that a slow observer slows the
  agent. `JsonlTracer` opens the file once per event. A queue with a background writer
  would decouple them, but adds threads and shutdown handling.

### D100. Events carry live objects; frozen is shallow
**Status:** open (made during implementation)
- `ToolCalled.call` is the same `ToolCall` the agent uses. An observer that mutates
  `call.arguments` would change the agent's data. Freezing only stops *reassigning* fields.
  Copying on emit would be safer but costs a copy per event.

### D101. No event for unexpected errors
**Status:** open (made during implementation)
- If a provider raises something that isn't `StopRun` (e.g. the `max_steps` `RuntimeError`,
  D90), the run aborts and observers never see `RunFinished`. A `RunFailed(error)` event
  emitted from `run()` would close the gap.

### D102. The events ↔ tools import cycle is broken with a `TYPE_CHECKING` import
**Status:** accepted (made during implementation)
- `events.py` only needs `Decision` as an annotation. With
  `from __future__ import annotations`, it never imports the tools package at runtime,
  so the Toolbox can import events at the top of its module.

### D103. `--steps` removed; a stage 7 bug fixed in the example
**Status:** accepted (made during implementation)
- The console printer shows every state, so `--steps` was redundant.
- **Bug found while editing:** the fallback report looped with `for provider, why in ...`,
  overwriting the `provider` variable that the cache summary read next. With
  `--fallback --cache` and a failure, it would have crashed. The loop now uses `link`.

### D104. Observers can watch but can't veto
**Status:** accepted (made during implementation)
- `UsageTracker` could almost be an observer of `ModelCalled`. But `BudgetGuard` must stop a
  call *before* it happens, and an observer only hears about events after the fact. This is
  why the budget is a proxy (D72), not an observer. Observer is for *reacting*, not *controlling*.

---

## Stage 11: Memento + Prototype

### D105. Checkpoints support conversation rewind, file rewind, save/resume and fork (your call)
**Status:** accepted
- Observed live: a run stopped by a tiny budget was resumed from its autosaved checkpoint
  in a new process. It continued with the next tool call and didn't repeat the first model call.

### D106. Checkpoints are JSON; `raw` is stored via `model_dump()` (your call)
**Status:** accepted; **live replay against Anthropic not yet verified**
- Anthropic's SDK blocks are dumped with `model_dump(mode="json", exclude_none=True)`, and the
  adapter replays the loaded dicts unchanged (tested offline with real `TextBlock` and
  `ToolUseBlock` objects).
- `exclude_none` avoids sending `null` for optional fields the API may not expect.
- **Unverified:** the Anthropic key was invalid during this stage, so a resumed Claude run
  (with thinking blocks) hasn't been sent back to the real API yet. Verify once the key works.

### D107. A fork copies the conversation and shares everything else unless overridden (your call)
**Status:** accepted
- It warns when the fork shares the original's Toolbox (same workspace, same undo history).

### D108. The memento is a transparent frozen dataclass, not an opaque object
**Status:** accepted (made during implementation)
- GoF's Memento is *opaque*: only the originator can read it. Here, serialization needs
  the fields, and Python can't enforce privacy anyway. The intent survives as a convention:
  only `Agent` builds and restores checkpoints, and everyone else just holds them.

### D109. Deep copies on capture *and* on restore
**Status:** accepted (made during implementation)
- Capture copies, so later changes to the agent don't alter the checkpoint. Restore copies,
  so changes after restoring don't alter it either, and the same checkpoint can be restored
  many times (both tested). The cost is two copies of the conversation per round trip.

### D110. Lifecycle states serialize themselves
**Status:** accepted (made during implementation)
- Each state's `snapshot()` returns only its own data (`ActingOnTools` → its pending calls,
  `Done` → the answer). `from_snapshot()` rebuilds it, so a run can resume with tool calls
  still pending. `from_snapshot` is a small `if` chain; a registry like stage 3's would be the
  next step if states multiply.

### D111. A `ToolMark` names its Toolbox; a foreign mark restores the conversation only
**Status:** accepted (made during implementation)
- Each Toolbox has a random `id`. A checkpoint from another Toolbox (a fork, or a file
  loaded in a new process) can't safely rewind files: its history positions refer to commands
  this Toolbox never ran. `restore()` warns and restores just the conversation.
- **Consequence:** resuming from disk should pass `files=False`, which the example does.
  Persisting the command history (D40) would be needed to rewind files across processes.

### D112. File rewind checks for irreversible actions before undoing anything
**Status:** accepted, with a known gap (made during implementation)
- `Toolbox.rewind_to()` scans the range first, and `Agent.restore()` rewinds files *before*
  touching the conversation. An irreversible action leaves everything exactly as it was (tested).
- **Gap:** an individual undo can still fail halfway, for example when a file changed since it
  was written (D35). Then earlier undos have already happened. True all-or-nothing would need
  a transaction or a redo log.

### D113. Rewound commands stay in the history, marked undone
**Status:** accepted (made during implementation)
- The history is an audit log: "written, then rewound" is more truthful than silently deleting
  the record. Later marks still work because positions only grow.

### D114. Atomic saves and a format version
**Status:** accepted (made during implementation)
- `save()` writes to a temporary file and renames it, so a crash mid-write never leaves half a
  checkpoint. A `version` field lets future formats be detected instead of misread.

### D115. `fork()` uses `copy.copy(self)`, so a fork of a subclass is that subclass
**Status:** accepted (made during implementation)
- This is Prototype's real advantage over calling a constructor: the copy keeps the original's
  concrete class and configuration without the caller knowing either (tested with `Shouty`).
- Overrides are limited to known attributes, so `fork(model=...)` raises instead of silently
  adding an attribute nobody reads.
- **Shared by default:** the provider, and with it any `UsageTracker` or `CircuitBreaker`
  inside. A fork's spend counts against the same budget, which is usually what you want.
- A fork never rewinds the original's files (`restore(files=False)`).

### D116. Autosave is an observer in the example, not an Agent feature
**Status:** accepted (made during implementation)
- It subscribes to `StateChanged` and saves after every non-final transition, and it deletes the
  file when the run finishes. The Agent didn't change, which shows patterns composing (Observer
  driving Memento).
- A resumed run emits no `RunStarted`, because it didn't start.

### D117. Checkpoints are taken between steps; resuming re-runs pending tool calls
**Status:** open (made during implementation)
- A checkpoint in `ActingOnTools` holds calls that haven't run yet. If a process crashes *while*
  tools are running (after a write, before the next save), resuming runs that write again.
  That's *at-least-once* execution. Exactly-once would need per-call records written before
  and after each tool runs.

### D118. Persisted checkpoints make asynchronous approval possible
**Status:** open (enabler for D91)
- A run could stop in `ActingOnTools` when approval is needed, save, exit, and resume after a
  human approves, even in another process. The missing piece is an `AwaitingApproval` state
  and an approver that says "later" instead of yes or no.

---

## Stage 12: Composite

### D119. A sub-agent is an `AgentTool`, a regular `Tool` (your call)
**Status:** accepted
- **Why:** the Toolbox, policies, events and history all work unchanged, because the parent
  can't tell a sub-agent from `add`. That uniformity *is* the Composite pattern: leaves (tools)
  and composites (agents with tools) share one interface, so trees build naturally.
- Observed live: the parent's context grew only by the researcher's final answer.

### D120. Each call runs a fresh copy of a prototype agent (your call)
**Status:** accepted
- `copy.copy(prototype)` (stage 11's Prototype) gives the same class and configuration with an
  empty conversation. The prototype itself never runs. Calls can't influence each other, and
  context stays small, which is the main reason harnesses use sub-agents.

### D121. `AgentTool.side_effects` is derived from its sub-agent's tools, recursively (your call)
**Status:** accepted
- This is the classic Composite *operation*: a property of the whole computed from its parts.
  A read-only researcher is read-only, so `AllowReadOnly` lets it run without asking (seen live).
  A sub-agent that can write needs approval, and that propagates up any depth of tree (tested).

### D122. Sub-agents share the parent's bus; events carry `agent` and `depth` (your call)
**Status:** accepted
- The console printer indents nested runs, and the JSONL trace records the tree.

### D123. Agent attribution uses a `ContextVar`, not parameters
**Status:** accepted (made during implementation)
- **Problem:** a sub-agent's tool calls go through a Toolbox (often a view of the parent's)
  that doesn't know who's calling. Passing "agent, depth" explicitly would change
  `execute()`, `ToolSet` and every wrapper.
- **Chosen:** each agent enters `agent_scope(name)` for its `start`/`step`/`restore`. A sub-agent
  runs *inside* its parent's tool call, so the innermost scope is always the agent doing the work,
  and the bus tags events from it.
- **Trade-off:** implicit context is invisible in signatures. It works, but nothing in
  `Toolbox.execute()` tells a reader that attribution happens. ContextVars are thread- and
  asyncio-safe, unlike a global.

### D124. Events have `agent`/`depth` fields with defaults, filled in by the bus
**Status:** accepted (made during implementation)
- Emitters didn't change, because the bus applies `dataclasses.replace()`. Events emitted outside
  any agent (e.g. a Toolbox used directly) keep `agent=""` and `depth=0`.
- Tests that compared whole events now compare the fields they care about.

### D125. `Tool` attributes are plain annotations, not `ClassVar`
**Status:** accepted (made during implementation)
- `AgentTool` sets `name`/`description` per instance and *computes* `side_effects` as a property.
  `ClassVar` told type checkers that wasn't allowed. Simple tools still set them as class attributes.

### D126. When side effects can't be determined, assume there are some
**Status:** accepted (made during implementation)
- A cycle (an agent that contains itself) or tools that can't be inspected count as side effects.
  This fails closed, consistent with D37, D48 and D58. A wrong "read-only" would skip approval.

### D127. An `AgentTool` call isn't undoable as a unit
**Status:** open (made during implementation)
- A sub-agent's writes are recorded in whichever Toolbox it used. Through a view of the parent's
  Toolbox they're in the parent's history and can be undone one by one. With its own Toolbox,
  they're in that Toolbox's history.
- **Option:** make `AgentTool` reversible by remembering its sub-Toolbox's mark and rewinding to it
  (stage 11's `rewind_to`), so "undo the delegation" becomes one step.

### D128. A depth limit (default 3) stops runaway recursion
**Status:** accepted (made during implementation)
- An agent that can call itself would otherwise recurse until the provider budget or Python's stack
  ran out. Past the limit, `run()` raises `RecursionError`, and the Toolbox turns it into error text
  for the model (tested).

### D129. Sub-agent copies share the prototype's provider (and everything shallow)
**Status:** accepted (made during implementation)
- Observed live: one `UsageTracker` counted all 4 model calls, the sub-agent's included, so one
  budget covers the whole tree. A breaker or cache inside the provider is shared too.
- `copy.copy` is shallow: the provider, the tools and the bus are shared, while `messages` and `state`
  are replaced on `start()`. A sub-agent with its own Toolbox needs its own prototype configured that way.

### D130. `Toolbox.add()` is public
**Status:** accepted (made during implementation)
- Needed so a sub-agent can get a view of the Toolbox that will contain it (create the Toolbox,
  build the view, then add the `AgentTool`). The constructor uses it, so duplicate checks live in one place.

### D131. A sub-agent's stop or failure becomes a tool result for the parent
**Status:** open for trees; teams stop immediately instead (D141)
- If a sub-agent hits the budget, it *returns* `"[stopped: budget] ..."`, which the parent sees as
  the tool's output. The parent then tries its own next call, which the shared budget also refuses.
  It works out, but a `StopRun` inside a sub-agent arguably should stop the whole tree immediately.

### D132. Nested events arrive in post-order
**Status:** accepted (made during implementation)
- The sub-agent's `ToolCalled` events arrive *before* the parent's `ToolCalled` for the `AgentTool`
  itself, because the outer call only finishes when the inner run does. Rebuilding the tree from a
  trace needs `depth` plus order. Stage 14's Visitor will walk that tree.

---

## Stage 13: Mediator

### D133. A peer team that talks only through a `Team` mediator (your call)
**Status:** accepted
- **Mediator vs Composite (stage 12):** in a tree, a parent *owns* its children and calls them.
  In a team, nobody owns anybody: members only get `send_message`, and the routing graph lives in
  one place. Changing who may talk to whom means editing `routes`, not the agents.
- Partly speculative when chosen (nothing in the project forced it), but it covers a real
  multi-agent shape trees can't: equals talking back and forth (review loops, handoffs).

### D134. Each member sees only messages addressed to it (your call)
**Status:** accepted
- Contexts stay small and roles stay clean. Only the mediator (`team.log`) sees everything.
- **Cost found live:** the reviewer didn't know the original task. See D142.

### D135. Members keep their conversation between turns: `Agent.follow_up()` (your call)
**Status:** accepted
- `follow_up(text)` continues a finished run with a new user message, so the writer revises with
  its earlier draft and the feedback in context. `max_steps` applies per turn, and each turn emits
  `RunStarted`.

### D136. Finishing is `approve()`: the result is the last message the finisher received (your call; found live)
**Status:** accepted
- **What happened:** with `finish(result)`, a live reviewer "approved" by passing its *own* rewritten
  slogan, which ignored the task's constraints and wasn't the writer's work.
- **Now:** `approve()` takes no text. The team's output is always a teammate's message.
- **Lesson:** when a role matters, enforce it in the mediator's API, not in the prompt.

### D137. Team tools are added by wrapping each member's `ToolSet`, on copies of the agents
**Status:** accepted (made during implementation)
- `_MemberTools` adds `send_message`/`approve` and delegates everything else to the member's own
  tools. It's a Decorator over `ToolSet`. The team holds `copy.copy`s of the agents, so the caller's
  agents are never modified (tested).
- Team tools skip the member's policy chain: they only queue a message for the mediator and touch
  nothing outside it.

### D138. Allowed recipients are both a schema `enum` and a server-side check
**Status:** accepted (made during implementation)
- The `enum` steers the model toward valid recipients. `_send()` still rejects anything else.
  The schema is a hint and the check is the enforcement, the same defense-in-depth idea as D75.

### D139. A member's turn ends when its own run finishes
**Status:** open (made during implementation)
- After `send_message`, the model gets "Message sent" and replies once more before its run ends.
  That's an extra short model call per turn (8 calls for 4 messages in the live run).
- **Alternative:** end the turn as soon as the member sends (a `StopRun`-like signal from the tool),
  which would halve the calls, at the cost of members never sending two messages in one turn.

### D140. Messages are delivered first in, first out; several sends in one turn are all delivered
**Status:** accepted (made during implementation)

### D141. A team ends on approval, `max_turns`, a dead end, or a stopped member
**Status:** accepted (made during implementation)
- **Dead end:** a member that finishes without sending or approving ends the team with
  `"[stopped: no messages] <its answer>"`.
- **Stopped member** (e.g. the shared budget): the whole team stops at once, unlike stage 12's
  trees (D131), where the parent carries on.

### D142. The mediator shares the team's brief on each member's first turn (found live)
**Status:** accepted
- **What happened:** with strict isolation (D134), the reviewer couldn't check "exactly 7 words"
  because it never saw the task. Telling the writer to forward it put the requirements *inside* the
  draft, and that text then became the approved result.
- **Now:** a member's first message is prefixed with `Team task: ...`. Sharing the brief is coordination,
  which is the mediator's job, while messages stay private.

### D143. Mechanical requirements belong in code, not in a reviewer's judgment
**Status:** open (found live)
- Live, one reviewer approved a 6-word slogan for a 7-word rule. Another flagged a correct 7-word draft as
  8 words. An LLM is unreliable at counting.
- **Option:** validators on `approve()`, e.g. `Team(..., validators=[exact_words(7)])`, that reject an
  approval with a concrete reason. Code checks what can be checked, and the LLM judges the rest.

### D144. `MessageRouted` is emitted by the mediator, outside any member's scope
**Status:** accepted (made during implementation)
- So it's tagged `agent=""`, or with the enclosing agent if a team runs inside one (e.g. a team behind an
  `AgentTool`). The console shows `── writer → reviewer: ...`.

---

## Stage 14: Visitor

### D145. Classic `accept`/`visit` double dispatch (your call)
**Status:** accepted
- **Options:** `node.accept(visitor)` → `visitor.visit_<type>(node)` · `match` statements in plain functions.
- **Why:** it shows the pattern itself. The trade-off is the *expression problem*: a new operation is one
  new class (demonstrated twice: a visitor written inside a test, and a throwaway one written live to
  debug a run), while a new node type touches the base visitor and every visitor that cares.

### D146. Two visitors: `CostSummary` and `HtmlReport` (your call)
**Status:** accepted
- Live: the summary's totals matched the run's own usage line exactly ($0.000760 over 4 calls), split
  between `agent` and `researcher`.
- **Observed value:** a live answer claimed 4 action items when the file had 2. Walking the trace
  showed `read_file` returned 2, the researcher reported 2, and the *parent* invented the other two.
  Without the tree you can't tell which layer went wrong.

### D147. The tree is rebuilt from event *records* (the JSONL format), not from event objects
**Status:** accepted (made during implementation)
- **Why:** one input format for files and, later, live streams. A live builder would just turn events
  into the same records the tracer writes.
- **Consequence:** the tracer's record keys are now a contract. Renaming an event field breaks old traces.
  A format version (like checkpoints, D114) would be the next step if traces need to last.

### D148. A nested run attaches to the *next* `ToolCalled` of the run that's open around it
**Status:** accepted, with a known dependency (made during implementation)
- Events arrive in post-order (D132), so the builder holds deeper runs as pending until their parent's
  tool call finishes.
- **Relies on sequential tools (D39):** with tools running concurrently, two sub-runs and two tool
  calls could interleave and pair up wrongly. Robust pairing would need `RunStarted` to carry the id of
  the tool call that started it.

### D149. `StateChanged` is left out of the tree
**Status:** accepted (made during implementation)
- Runs, model calls and tool calls already tell the story; state changes would double the nodes.

### D150. Team turns are top-level runs, with messages between them
**Status:** accepted (made during implementation)
- Each `follow_up` turn is its own `RunNode`. A member's turns aren't grouped under the member, so the
  tree shows the conversation in the order it happened.

### D151. The base visitor walks children by default; overrides must call `super()` to keep walking
**Status:** accepted (made during implementation)
- Visitors override only what they need. The risk is that an override that forgets `super()` silently
  skips that subtree, for example missing a sub-agent's costs. `CostSummary.visit_tool` calls it explicitly.

### D152. Visitors accumulate state; results are read after `accept()`
**Status:** accepted (made during implementation)
- `CostSummary().by_agent`, `HtmlReport().page()`. Returning values from every `visit_*` would make
  combining results awkward. The cost is one visitor instance per traversal.

### D153. Visitors compose: the HTML report runs a cost summary per run
**Status:** accepted (made during implementation)
- Each run's header shows its cost *including sub-agents*. Re-walking each subtree is quadratic for deep
  trees, which is fine at trace sizes. A single pass computing costs bottom-up would scale better.

### D154. The HTML report escapes all trace text
**Status:** accepted (made during implementation)
- Tool outputs and model text are untrusted: a file containing `<script>` must not run when you open the
  report (tested). The page is self-contained, with light and dark styles.

### D155. Command line: `python -m miniharness.trace FILE [--html OUT]`
**Status:** accepted (made during implementation)
