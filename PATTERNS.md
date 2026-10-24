# Pattern journal

One entry per pattern, written when you apply it. Template:

```
## <Pattern> (stage N)
- Problem I hit:
- What the code looked like before:
- Alternatives I considered:
- What I chose and why:
- What it cost (indirection, classes, readability):
- Would Python idioms have done it more simply?
```

---

## Template Method (stage 1, scaffolded)

- **Problem:** every agent variant (ReAct, planner, human-in-the-loop) runs the
  same loop of think → act → repeat, but differs in the details.
- **Shape:** `Agent.run()` holds the fixed loop; `initial_messages`, `think`,
  `act` and `finish` are hooks a subclass overrides.
- **Try it:** write a `LoggingAgent(Agent)` that overrides only `act()` to print
  each tool call. The loop itself stays untouched.
- **Watch for:** inheritance limits you to one variation axis per subclass.
  Stage 2 shows the composition alternative, Strategy.

---

## Strategy (stage 2)

- **Problem:** `call_llm` branched on a provider string; every new provider meant editing it.
- **Shape:** `Provider` protocol with `complete(messages, tools)`. `Agent` holds
  one and never asks which it is. Swapping LLMs means passing a different object.
- **vs Template Method:** both vary one step of an algorithm. Template Method varies
  it by *inheritance* (override `think()`); Strategy varies it by *composition* (pass a
  provider). Composition wins here because the provider choice is independent of the
  agent type: a `ReActAgent` and a `PlannerAgent` can each use any provider.
- **Your notes:**

## Adapter (stage 2)

- **Problem:** two SDKs with incompatible message formats. The harness wants one.
- **Shape:** `OpenAIChatAdapter` and `AnthropicMessagesAdapter` convert both ways
  between our `Message`/`ToolCall` types and each wire format. Pure functions, no network.
- **Watch for:** `Message.raw` is where the adapter abstraction *leaks* (DECISIONS.md D8).
  Every adapter eventually meets something the common interface can't express.
- **Your notes:**

---

## Stage 2 smells: before → after

- [x] `call_llm` branches on a provider string → one class per provider
- [x] Clients rebuilt on every call → built once per provider
- [x] Translation can't be tested offline → pure adapters + injected fake clients
- [x] `MOCK_RESPONSES` global → `MockProvider(responses)` instance
- [x] `Agent.__init__` knows default models → each provider owns its default
- [ ] `Message.raw` leaks Anthropic details → still open (D8)
- [x] *New smell:* `examples/hello.py` branches on a provider string → fixed in stage 3

---

## Factory (stage 3)

- **Problem:** every caller that turned a name into a provider needed its own `if/elif`.
- **Shape:** `create_provider("openrouter:qwen/qwen3-coder")` looks the name up in
  a registry that classes fill with `@register_provider("openrouter")`.
- **Simple factory vs Factory Method vs Abstract Factory:**
  - *Simple factory:* one function maps names to constructors. That's what we have,
    plus self-registration.
  - *Factory Method (GoF):* subclasses override a creation method, e.g. an
    `Agent.create_provider()` hook. It varies *what gets built* through inheritance,
    like Template Method does for steps.
  - *Abstract Factory (GoF):* one object builds a whole family of matching parts.
    Not needed yet (DECISIONS.md D14).
- **Python note:** classes are callable objects, so a dict of classes already *is*
  a factory. The decorator only automates filling the dict.
- **Smell it introduced:** a global mutable registry (D17).
- **Your notes:**

---

## Builder (stage 4)

- **Problem:** system prompts in real harnesses are assembled from parts, and the
  *order* matters: prompt caching only reuses an unchanged prefix, so volatile facts
  (date, cwd) must come last.
- **Shape:** `SystemPromptBuilder` collects sections in any order; `build()` validates
  (identity required) and renders them in a fixed stable-to-volatile order.
  `default_prompt()` is the **Director**, a reusable recipe.
- **When Builder is worth it in Python:** not for "many constructor args" (kwargs and
  dataclasses already handle that). It's worth it when construction has **rules**:
  ordering, validation, or several representations of the same parts.
- **Try it:** add a `.persona()` section, or decide where `.examples()` (few-shot)
  belongs in the order and why.
- **Your notes:**

---

## Command (stage 5)

- **Problem:** a tool call was a dict lookup plus a function call. Nothing recorded
  what happened, and nothing could be reversed.
- **Roles:**
  - *Command* = `ToolCommand`: one call packaged with its tool, arguments, result
    and undo info. It's an object you can store, inspect, replay or undo.
  - *Invoker* = `Toolbox`: runs commands and keeps the history.
  - *Receiver* = the workspace on disk, which actually changes.
  - *Client* = the Agent, which turns model output into commands.
- **The key insight:** turning a *call* into an *object* is what makes logging,
  queuing, replay and undo possible. Without that object, there's nothing to hold on to.
- **Two undo strategies:** snapshot (save prior state, restore it) vs compensating
  command (run the inverse action). See DECISIONS.md D33, and the Saga pattern.
- **Harness connection:** Claude Code's rewind/checkpoints are this pattern applied to
  file edits.
- **Try it:** add an `AppendFile` tool. What's its undo info? Is a snapshot or an
  inverse cheaper here?
- **Your notes:**

---

## Decorator (stage 6)

- **Problem:** cost tracking, budgets, retries and caching all apply to *every*
  provider. Putting them inside each provider duplicates code; subclassing every
  combination (`CachedRetryingTrackedOpenRouter`) explodes.
- **Shape:** each wrapper takes a Provider, *is* a Provider, adds one behavior, and
  delegates the rest. `DiskCache(Retry(BudgetGuard(UsageTracker(base))))`.
- **The surprise:** order is behavior. Cache outside the tracker means hits are free;
  cache inside means they're counted twice. Tests pin both (DECISIONS.md D46).
- **Decorator vs Python `@decorator`:** the same name for different ideas. GoF wraps
  objects at runtime; `@` wraps functions at definition time.
- **Decorator vs Proxy (stage 8):** structurally identical. The difference is intent:
  a Decorator *adds* behavior, while a Proxy *controls access* to the same behavior.
  `BudgetGuard` arguably leans toward Proxy. Keep that in mind for stage 8.
- **Try it:** write a `Timing` wrapper that records the latency of each call. Where in the
  stack should it go to measure network time only, and where to include the cache?
- **Your notes:**

---

## Chain of Responsibility (stage 7)

- **Problem:** several independent rules decide whether a tool call may run
  (deny list, quota, read-only, ask a human). Hard-coding them as one `if` ladder
  in the Toolbox mixes every rule together.
- **Shape:** `PolicyChain([DenyTools, MaxCalls, AllowReadOnly, AskBeforeSideEffects])`.
  Each policy returns a `Decision` or `None`, and the first decision wins.
  `FallbackChain([anthropic, openrouter])` does the same for providers: the first
  one that answers wins.
- **CoR vs Decorator:** they look alike, since both are sequences of objects with
  the same interface. In a Decorator, every layer runs. In a Chain, the request stops
  at the first handler that takes it.
- **Live lesson:** the fallback chain hid an invalid API key (DECISIONS.md D63). A chain
  must be precise about what counts as "not mine, pass it on".
- **Harness connection:** Claude Code's permission rules (deny → ask → allow) are a policy
  chain. OpenRouter's `models: [...]` fallback is the same pattern running on the server.
- **Try it:** write a `DenyPaths` policy that blocks `write_file` outside a `notes/`
  folder. Where in the chain does it go, and why?
- **Your notes:**

---

## Proxy (stage 8)

- **Problem:** (1) building a provider needs its API key and client up front, even for a
  fallback that's never used; (2) some agents should only be able to *see* some tools.
- **Shape:**
  - *Virtual proxy:* `LazyProvider` stands in for a provider and builds it on first use.
  - *Protection proxy:* `ToolboxView` stands in for a Toolbox and exposes only allowed tools.
    `BudgetGuard` was one all along (DECISIONS.md D72).
  - *Remote proxy* (not built): a local object whose work happens elsewhere, as MCP tools do.
- **Proxy vs Decorator:** identical structure, different intent. Ask whether the wrapper
  changes *what happens* (decorator) or *whether and when it can happen* (proxy).
- **Live lesson:** with a read-only view, the model never tried to write. It couldn't see
  the tool, so no denial was needed. Hiding is stronger than refusing.
- **Smell:** introspection breaks transparency. Code that unwraps wrappers had to learn
  about the lazy proxy (D73).
- **Try it:** write a `LoggingToolSet` that records every call. Is that a proxy or a
  decorator? Then write one that requires approval. What changed?
- **Your notes:**

---

## State (stage 9)

- **Problem:** (1) the fallback retried a dead provider on every turn (D65). The fix,
  a circuit breaker, behaves completely differently depending on its history. (2) The
  agent's loop had implicit phases you couldn't see or step through.
- **Shape:** each state is an object with its own `call()`/`step()` that returns or sets the
  next state. `CircuitBreaker`: `Closed → Open → HalfOpen → Closed/Open`. Agent:
  `Idle → Thinking ⇄ ActingOnTools → Done/Stopped`.
- **State vs Strategy:** both swap an object to change behavior. With Strategy, the *client*
  picks the object and it rarely changes. With State, the *object changes itself* as things
  happen.
- **State-local data:** `Closed` owns the failure count and `Open` owns `opened_at`, so
  entering a state resets its data for free (DECISIONS.md D83).
- **Patterns compose:** the breaker is a Proxy by intent and State by implementation.
  The lifecycle states call Template Method hooks.
- **Try it:** add a `Paused` agent state that `step()` won't leave until `resume()` is
  called. What would it need to survive a process restart? (That's stage 11.)
- **Your notes:**

---

## Observer (stage 10)

- **Problem:** to watch the agent work (console, trace file, tests), you had to edit the
  Agent or reconstruct events from `agent.messages` after the run.
- **Shape:** the Agent and Toolbox `emit()` typed events (`StateChanged`, `ModelCalled`,
  `ToolCalled`, ...) on a shared `EventBus`. Subscribers are plain callables. Emitters don't
  know who's listening or whether anyone is.
- **The key property:** subjects don't depend on observers. A broken observer can't break
  the run (DECISIONS.md D95), and an observer can't veto anything (D104).
- **Observer vs Proxy:** both can sit next to a provider. A proxy runs *before* the call and
  can stop it. An observer hears *after* and can only react.
- **Patterns compose:** stage 9's lifecycle made this easy, because every transition already
  went through one method.
- **Try it:** write a `Stats` observer that counts tool calls per tool and prints a summary
  on `RunFinished`. Did you need to touch the Agent?
- **Your notes:**
