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
- **Shape:** each state is an object with its own behavior that returns or sets the next state:
  the breaker's states have `admit()`/`succeeded()`/`failed()` hooks (D161), the agent's states a
  `step()`. `CircuitBreaker`: `Closed → Open → HalfOpen → Closed/Open`. Agent:
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

---

## Memento + Prototype (stage 11)

- **Problem:** no way to go back (rewind a conversation and its file changes), to survive a stop
  (resume after a budget stop or a crash), or to try alternatives from the same point (fork).
- **Memento:** `agent.checkpoint()` returns a `Checkpoint` (a deep-copied snapshot of messages,
  lifecycle state, model-call count and a `ToolMark`). `agent.restore(cp)` puts it all back,
  undoing later file changes through stage 5's command history. `save()`/`load()` persist it.
- **Prototype:** `agent.fork(cp, provider=...)` copies the agent, keeping its class and settings,
  and continues independently.
- **Roles:** *Originator* = Agent (creates and restores). *Memento* = Checkpoint. *Caretaker* =
  whoever holds it (the autosave observer, a test, you).
- **Patterns compose:** rewind = Memento (conversation) + Command (file undo). Autosave = Observer
  driving Memento. Resume relies on State (each state snapshots itself).
- **Harness connection:** Claude Code's rewind restores the conversation *and* the code together.
  That's D105 plus file rewind.
- **Try it:** take a checkpoint, fork it onto two different models, run both, and compare
  their answers and costs.
- **Your notes:**

---

## Composite (stage 12)

- **Problem:** delegating work to a sub-agent, such as a cheap read-only researcher, without the
  parent's context filling up with the sub-agent's turns, and without new machinery for
  policies, events or undo.
- **Shape:** `AgentTool(name, description, prototype_agent)` is a `Tool`. Its `run(task)` drives a
  fresh copy of an agent whose own tools may include more `AgentTool`s: a tree.
- **The Composite operation:** `side_effects` is computed from the children, recursively. Policies
  then treat a whole subtree like a single tool (DECISIONS.md D121).
- **Patterns compose:** Prototype (fresh copies), Proxy (`ToolboxView` for read-only sub-agents),
  Chain of Responsibility (policies decide on the derived property), Observer (one bus, tagged
  with depth).
- **Harness connection:** Claude Code's sub-agents (the Agent tool, formerly Task) are this: an agent exposed to its
  parent as a tool, returning only a summary.
- **Try it:** give the researcher its own cheaper model (`fork(provider=...)` on the prototype).
  Where does the cost show up now, and does the shared budget still apply?
- **Your notes:**

---

## Mediator (stage 13)

- **Problem:** agents that need to talk *as equals*, like a writer and a reviewer going back and forth.
  A tree (stage 12) only lets a parent call down. Wiring peers to each other directly makes every
  agent know every other one.
- **Shape:** `Team(members, routes, finishers)`. Members get `send_message(to, text)` (limited by
  `routes`) and finishers get `approve()`. The team delivers messages, runs turns and decides when
  it's done. Members hold no references to each other.
- **Mediator vs Observer:** both decouple senders from receivers. Observer *broadcasts* to whoever
  subscribed, and the subject doesn't care who. A Mediator *routes* with knowledge of every
  participant and the rules between them.
- **Live lessons:** a reviewer substituted its own text (so `approve()` replaced `finish(result)`,
  D136), and isolation hid the brief from the reviewer (so the mediator now shares it, D142).
  Roles are enforced by the mediator's API, not by prompts.
- **Harness connection:** "handoff" and "supervisor" multi-agent setups (the OpenAI Agents SDK's
  handoffs, LangGraph supervisors) are mediators: the routing lives outside the agents.
- **Try it:** add an `editor` member between writer and reviewer by editing only `routes`. Did any
  agent's code or prompt need to change?
- **Your notes:**

---

## Visitor (stage 14)

- **Problem:** many operations over the same trace tree (totals per agent, an HTML report, and later
  exports and checks). Putting each as a method on every node class would bloat the nodes and mix
  unrelated concerns.
- **Shape:** nodes (`RunNode`, `ModelCallNode`, `ToolCallNode`, `MessageNode`) only implement
  `accept(visitor)`, which calls `visitor.visit_<type>(self)`. Operations are `TraceVisitor`
  subclasses that override the visits they care about.
- **Double dispatch:** which code runs depends on *two* types, the node's (via `accept`) and the
  visitor's (via the method it defines).
- **The expression problem:** Visitor makes new *operations* cheap and new *node types* expensive.
  Plain methods on nodes are the opposite. Choose based on which one will grow.
- **Live lesson:** a five-line throwaway visitor found which layer invented two "action items" (the
  parent, not the sub-agent). See DECISIONS.md D146.
- **Try it:** write a `SlowestCalls` visitor that lists the three slowest model calls with their agent.
  Did you touch any node class?
- **Your notes:**

---

## Iterator (stage 15)

- **Problem:** everything returned only when it was finished. You stared at a blank terminal until the whole
  answer arrived, and the only way to watch a run was to subscribe to it (push), with no way to drive it
  from a plain loop or stop it mid-answer.
- **Shape:** two iterators. `provider.stream()` yields `TextDelta`s, then one `Completed(response)`.
  `agent.iter_run(task)` yields every event of the run (`TokenStreamed`, `ModelCalled`, `ToolCalled`,
  ...) as it happens. Inside, each state's `iter_step()` is a generator that pauses at every token and
  *returns* the next state.
- **The pattern dissolved into the language:** GoF Iterator is a class with `has_next()`/`next()` that
  keeps traversal state outside the collection. A Python generator *is* that class, written by the
  compiler: the paused stack frame holds the traversal state, and `yield` is `next()`. Not one
  `__next__` was hand-written this stage.
- **Iterator vs Observer (pull vs push):** the same events, two directions of control. With Observer, the
  subject decides when you hear about something. With Iterator, you decide when the subject continues.
  Pull gives backpressure and `break` (cancellation) for free. Push reaches every listener, including
  sub-agents mid-tool-call (DECISIONS.md D163). `iter_run()` is built *on* the bus: a buffer subscriber,
  emptied every time the agent pauses.
- **Patterns compose, and collide:** every Decorator needed a streaming path, and forwarding
  `stream()` by default would have silently skipped the budget (D158). A stream's outcome is only known
  at the end, which forced the circuit breaker's State classes into before/after hooks (D161), and
  "retry" stops meaning anything once the user has seen half an answer (D159).
- **Live lessons:** stopping `examples/stream.py` after 12 words left the agent in `thinking`, resumable,
  with the HTTP stream closed. But the run's cost became *unknown*, because the usage only arrives at
  the end (D160). Separately, a ContextVar held across a `yield` leaks into the caller (D164).
- **Harness connection:** Claude Code and the Agent SDKs stream message deltas to the UI and expose the
  agent loop as an async iterator of messages (`for await (const message of query(...))`). That's
  `iter_run()`. Their "interrupt" is our `break`.
- **Try it:** give `Trace` a `walk()` generator that yields every node depth-first (the classic Iterator
  over a Composite), then rewrite `CostSummary` as a loop over `walk()`. What did you lose compared with
  the Visitor's double dispatch, and what got simpler?
- **Your notes:**

---

## Facade (stage 16)

- **Problem:** by stage 15, a capable agent meant hand-composing about ten objects in the right order:
  a provider inside five wrapper layers (in the D46 order), a `Toolbox` with a policy chain and an
  approver, one event bus passed to *both* the agent and the toolbox (forget one and `ToolCalled`
  silently disappears, D98), observers, a prompt from the builder, an autosave observer and sub-agents.
  `examples/hello.py` was 165 lines, mostly wiring, and every new script copied it.
- **Shape:** `Harness(model, budget=..., workspace=..., approve=...)` builds everything from flat keyword
  arguments with safe defaults, then offers a narrow API: `run()`, `follow_up()`, `stream()`,
  `resume()`, `add_helper()`, `rewind()`, `report()`. The provider stack recipe moved to
  `build_stack()`, a Director function the facade *uses* and other code can use without it.
- **A facade simplifies; it doesn't lock anything away:** `h.agent`, `h.toolbox`, `h.stack.tracker` and
  `h.events` are public. The advanced case starts from a working harness instead of a blank file, and
  `stream.py` still builds an `Agent` by hand. GoF is explicit that clients may bypass the facade.
- **Facade vs Mediator:** both sit in front of a group of objects. A Mediator (stage 13) sits *between*
  peers that talk to each other through it. The peers know the mediator, and it carries their
  conversation. A Facade sits *in front of* a subsystem for an outside client. The subsystem doesn't
  know the facade exists, and the agent, toolbox and wrappers didn't change at all this stage.
- **Facade vs Builder/Director:** a Builder (stage 4) assembles *one* complex product under rules and is
  done. A Facade is still there after construction, as the simple way to *use* many objects. Here they
  cooperate: the facade calls two Directors (`default_prompt()`, `build_stack()`), and its value is the
  API afterwards (`report()`, `rewind()`).
- **Defaults are the facade's real design work:** the parts can do anything, so the facade decides what
  happens when the caller says nothing. Here, side effects are denied without `approve=` (a library
  never calls `input()`), every harness has a $0.05 budget, and file tools need a workspace.
- **Live lessons:** the defaults compose in ways the parts didn't. Breaking out of `h.stream()` makes the
  next call stop on `budget`, because the abandoned call's cost is unknown and the default budget fails
  closed (D179). Moving the checkpoint code into the facade exposed a bug in the old example: a helper
  finishing deleted the main run's checkpoint (D182). And `load_dotenv()` searches from the *script's*
  folder, so the facade leaves `.env` to the application (D181).
- **Harness connection:** the Claude Agent SDK's `query(prompt, options)` and `ClaudeSDKClient`, the
  OpenAI Agents SDK's `Runner.run(agent, input)`, and LangChain's `create_agent(...)` are facades over
  model clients, tool loops, permissions, hooks and sessions. Each one defines a permission mode and a
  max-turns default, and you drop down to the parts when the defaults stop fitting.
- **Try it:** write `examples/review.py` in under 20 lines that asks a `Harness` with a read-only helper to
  review a file in `workspace/`, then prints `h.report()`. Which subsystem did you have to reach *past*
  the facade for, and should that become a facade argument or stay an escape hatch?
- **Your notes:**

---

## Bridge (bonus stage)

- **Problem:** this journal promised "a `ReActAgent` and a `PlannerAgent` can each use any provider"
  back in stage 2, but there was only ever one agent class. The provider side had grown into a whole
  hierarchy (three providers, seven wrappers); the agent side hadn't grown at all. Adding agent types
  naively (an `OpenRouterPlanner`, an `AnthropicPlanner`, ...) is the N × M class explosion Bridge exists
  to prevent.
- **Shape:** the *abstraction* is `Agent`, the *implementor* is the `Provider` protocol, and the agent
  holds one by composition. `PlannerAgent` and `ReviewerAgent` (agent_types.py) are *refined
  abstractions*: they reshape the loop through two new Template Method hooks, `first_state()` (a
  planner starts in a `Planning` state: one tool-less call) and `after_answer()` (a reviewer sends its
  draft back for one review round). The concrete implementors (OpenRouter, Anthropic, Mock, and every
  wrapper) needed no change. All model calls go through one `model_call()` helper: the abstraction's
  operations are written in terms of the implementor's primitive, `complete()`/`stream()`.
- **Bridge vs Strategy:** the code is the same shape (an object holding an interchangeable
  collaborator). The difference is intent and the number of hierarchies. Strategy: *one* context
  class swaps *one* algorithm (stage 2: which LLM answers). Bridge: *two* hierarchies that are both
  expected to grow, joined by composition so they grow independently. Until a second agent type
  existed, this codebase only had a Strategy. Writing `PlannerAgent` didn't add a single line to the
  provider side, and that's the test that it's a Bridge.
- **Bridge vs Adapter:** Adapter (stage 2) makes *existing* incompatible interfaces fit, after the
  fact. Bridge is designed *up front* so that two sides never need fitting. Here they meet: the
  adapters sit *inside* the concrete implementors.
- **Live lesson:** the same task (`(17 * 23) + 4`) took 2 / 3 / 4 model calls and $0.00045 / $0.00062 /
  $0.00095 as plain / planner / reviewer. And self-review shares the model's blind spots: asked for
  Canberra's population, the reviewer kept an unverified number and only added a hedge (D197). The
  Bridge makes "reviewer × any provider" free, but a critic on a *different* provider would need a
  second implementor reference.
- **Template Method, State and Bridge together:** the new types are subclasses (Template Method hooks),
  the planning call is a lifecycle state (State), and the axis they vary is independent of the provider
  (Bridge). Because planning is a state, it streams, is traced and checkpoints for free. Doing it inside
  `initial_messages()` would have hidden it from the trace's cost summary (D189).
- **Harness connection:** agent frameworks separate "agent architecture" from "model client" the same
  way. LangGraph's prebuilt ReAct agent and its plan-and-execute and reflection recipes all take any chat
  model; the OpenAI Agents SDK's `Agent` takes a `model` that can be any `Model` implementation
  (LiteLLM for other providers). `Harness("anthropic", agent_type=PlannerAgent)` is that split.
- **Try it:** write a `ConfirmingAgent` that, in `after_answer()`, asks a human (via `input()`) whether
  the answer is good enough and, if not, appends their feedback and returns `Thinking()`. Run it on
  `mock` and `openrouter`. Did you touch `providers/`? Then try a `PlannerReviewerAgent(PlannerAgent,
  ReviewerAgent)`: does multiple inheritance compose the two hooks, and when would composition (D189)
  have been better?
- **Your notes:**

---

## Singleton → dependency injection (bonus stage)

- **Problem:** the last piece of hidden global state was the provider registry, a module-level
  `_REGISTRY` dict that `@register_provider` filled at import time and `create_provider` read
  (D17). Every caller reached *out* for it, so nothing could hand them a different one. A test that
  registered a provider had to `monkeypatch` the module to stop it leaking into every later test,
  the same pain the `MOCK_RESPONSES` (stage 2) and `TOOLS` (stage 5) globals caused before they went.
- **Shape:** `ProviderRegistry` is an ordinary class (`add`, `register` decorator, `create`, `names`,
  `copy`). The built-ins register into one ordinary instance, `default_registry`, and
  `create_provider`/`register_provider` are one-line delegates to it, so the convenient API didn't
  change. Everything that turns a spec into a provider takes `registry=`: `build_stack`,
  `lazy_provider`, `Harness`. A test copies the default, registers into the copy, and passes it in:
  no monkeypatch, no cleanup. `tests/test_singleton.py` keeps a textbook `__new__` Singleton as a
  runnable specimen, with the same scenarios written both ways.
- **Singleton vs DI:** a Singleton answers "how do I get *the* registry?" with "ask the class, it
  always returns the same one". DI answers "you don't get it, you're *given* one". The Singleton's
  costs are all visible in the specimen: hidden dependencies (nothing in a signature says it needs a
  registry), shared mutable state (a "fresh" instance carries everyone's changes), order-dependent
  tests and a reset fixture on every test, and no way to have two (one test's registry vs another's,
  one harness's vs another's). The honest caveat: `default_registry` is still a global object. What
  changed is the *direction of the dependency*: the global used to be the only option, now it's just
  the default argument, and every constructor that needs a registry says so.
- **Singleton vs ContextVar:** `events.agent_scope` is module-level too, and it stays. A ContextVar
  holds *facts about the current execution* (which agent is running, how deep), with a separate
  value per thread or asyncio task, set and reset by a `with`. It's not configuration anyone would
  want to swap, so there's nothing to inject. Rule of thumb: inject what an object needs to do its
  job; use a ContextVar for "where am I in the call stack" (request ids, trace spans, the running
  agent). Using a ContextVar for the registry (`with use_registry(r):`) was rejected: the dependency
  would be invisible again, only scoped (D203, D210).
- **The same rule, applied to D98:** *whoever creates an object wires it.* `Agent(provider)` builds its
  default Toolbox itself, so it now gives it its own event bus; until this stage, `ToolCalled` was
  silently lost on exactly that shortest path. A Toolbox you pass in is yours to wire: the Agent
  doesn't reach into objects it was handed (D76, D204).
- **Live lesson:** an alias that exists in only one registry (`cheap` → OpenRouter with a default
  model, a lambda registered in three lines) ran a tool-using task through `Harness("cheap",
  registry=mine)`, with a lazy `cheap:qwen/...` fallback that was never built; `Harness("cheap")` without
  it failed at startup, and the default registry was unchanged afterwards. And a plain `Agent` now
  reports `ToolCalled(multiply → 399)` without any manual wiring.
- **Where Python dissolves the pattern:** a module *is* a singleton (imported once, cached in
  `sys.modules`), so the Pythonic "Singleton" is a module-level object, which is exactly what
  `_REGISTRY` was. That's why the `__new__` class form is rare in Python code, and why removing the
  pattern here meant changing who *reaches for* the object, not deleting a class.
- **Harness connection:** frameworks keep the global for convenience and inject for control.
  pydantic-ai and LangChain's `init_chat_model` build models from `"provider:model"` strings via a
  built-in lookup, but every agent also accepts a ready model object. The OpenAI Agents SDK has
  `set_default_openai_client()` (a global default) next to a per-agent `model=` and a per-run
  `RunConfig(model_provider=...)` (injection). `default_registry` + `registry=` is the same split.
- **Try it:** write a test that runs two `Harness` objects side by side, each with its own registry
  where `"main"` means a different scripted provider, and check that each answers from its own. Then
  try the same with only the default registry: what would you have to monkeypatch, and could the two
  harnesses even coexist? Finally, find a place in your own agent code where something reaches for a
  global client or config, and write down who should create it and pass it in.
- **Your notes:**
