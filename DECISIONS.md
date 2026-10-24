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
**Status:** open (deliberately deferred)
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
**Status:** open
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
