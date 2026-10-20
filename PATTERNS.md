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

## Smells waiting for stage 2 (fill in your own observations)

- [ ] `call_llm` branches on a provider string; adding one means editing it
- [ ] Clients are rebuilt on every call
- [ ] Translation code is inline, so it can't be unit-tested offline
- [ ] `MOCK_RESPONSES` is a global that tests must clear
- [ ] `Agent.__init__` duplicates provider knowledge (default models)
- [ ] `Message.raw` only makes sense for Anthropic: a leaky abstraction?
