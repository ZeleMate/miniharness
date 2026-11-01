# Chapter 4. A prompt with assembly rules

*Pattern: [Builder](https://refactoring.guru/design-patterns/builder). Code: `src/miniharness/prompts.py`.*

## Questioning the pattern first

The textbook use of Builder, a fluent builder because a constructor has many arguments, makes little sense
in Python. Keyword arguments and dataclasses already do that job:

```python
agent = Agent(provider, system_prompt="Be brief.", max_steps=5)  # already readable
```

So there are three options: a fluent `Agent.builder()` (which would mostly show why Python rarely needs
one), skipping the pattern, or finding a place where construction has real *rules*. The code takes the
third (D21).

## The real rule: stable first, volatile last

Real harnesses assemble the system prompt from sections: who the agent is, how to use tools, task
instructions, and environment facts like the date and the working directory. And the **order matters**,
because **prompt caching reuses only an unchanged prefix.** Put the timestamp at the top, and the cached
prefix breaks on every request.

That's a genuine assembly rule, and enforcing assembly rules is what Builder is for:

```python
prompt = (
    SystemPromptBuilder()
    .environment(date="2026-10-25")  # called first...
    .instructions("Be brief.")
    .identity("You are a careful assistant.")
    .build()
)  # ...rendered last
```

Whatever order you call the methods in, `build()` always renders identity, then tool rules, then
instructions, and the environment last. The builder owns the order, so callers can't get it wrong (D23).
It also validates: a prompt without an identity raises an error at `build()`, and empty sections are left
out (D27).

## The Director

GoF's Builder has a companion, the **Director**, which knows a standard recipe. In Python it's just a
function, `default_prompt()`, that returns a pre-filled builder (D26). It returns the *builder* rather than
the finished string, so callers can extend the recipe before building:

```python
default_prompt().instructions("Answer in plain text. No LaTeX.").build()
```

That one instruction removes the LaTeX answers some models give (chapter 1), and it shows the Template
Method hooks and the Builder working together: the agent's default prompt comes from the Director.

## Smaller decisions with real consequences

- **Mutable or immutable builder?** Methods mutate and return `self`, the classic fluent style (D22). The
  cost is that a half-built builder can't be safely shared, because branching off it changes the original.
  The Director sidesteps that by returning a fresh builder every time.
- **`tool_rules()` takes guidance text, not tool schemas** (D24). The API already sends the schemas through
  its `tools` field, so repeating them in the prompt pays for the same tokens twice and can drift out of
  sync.
- **A date, not a timestamp** (D28). The coarser value breaks the cache once a day instead of on every call.
  Environment keys are sorted, so the same facts always render as the same bytes.
- **The output is a plain string** (D25, open). A Builder can also produce *different representations* of
  the same parts. A structured version, stable block plus volatile block, would let the Anthropic adapter
  put a cache breakpoint between them.

## The one thing to remember

**In Python, a Builder is worth it when construction has rules, not when a constructor has many
arguments.** Ordering, validation or several output formats justify it; a long argument list doesn't.

## Questions to think about

- Where in the order would a few-shot `examples()` section go, and why?
- Look at a prompt in your own work. Does anything volatile sit above something stable?
