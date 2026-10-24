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
