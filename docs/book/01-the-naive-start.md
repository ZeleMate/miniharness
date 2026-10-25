# Chapter 1. The naive start: a loop and an ugly function

*Pattern: Template Method. Code: `src/miniharness/agent.py`.*

## The smallest thing that works

Every agent harness, however sophisticated, has the same loop at its heart:

1. Send the conversation to the model.
2. If the model asked for tools, run them, add their results to the conversation, and go back to 1.
3. Otherwise, the model's reply is the answer.

The first scaffold was exactly that loop, plus a handful of neutral data types that the rest of the code
would speak: a `Message` (a role, some text, maybe tool calls), a `ToolCall` (an id, a name, arguments),
and an `LLMResponse` (the assistant's message plus *why* it stopped: finished, wants tools, ran out of
tokens). Three tools to start with: `add`, `multiply` and `current_time`. And a `MockProvider` that replays
scripted replies, so the loop could be tested without spending a cent.

## Template Method: a fixed skeleton with replaceable steps

The loop was written so its *structure* was fixed, but each step was a method a subclass could override:

```python
class Agent:
    def run(self, task):
        self.messages = self.initial_messages(task)
        for _ in range(self.max_steps):
            response = self.think(self.messages)
            self.messages.append(response.message)
            if response.stop_reason != "tool_calls":
                return self.finish(response)
            self.messages.extend(self.act(response.message.tool_calls))
```

`run()` is the *template method*. `initial_messages`, `think`, `act` and `finish` are the *hooks*. Want an
agent that logs every tool call? Override `act()`. Want a different final format? Override `finish()`.
The loop itself never changes.

This is the oldest trick in object-oriented design, and it has a well-known limit: inheritance gives you
**one axis of variation per subclass**. A `LoggingAgent` and a `PoliteAgent` can't be combined without a
third class. That limit is exactly why the next chapter reached for composition instead.

The hooks proved durable, though. Seventeen stages later, the Bridge chapter added two more
(`first_state` and `after_answer`) to build new kinds of agents, and the lifecycle states of chapter 9 call
these same hooks, so every subclass kept working through every refactor.

## The deliberately ugly part

The provider code was written badly *on purpose*. One function did everything:

```python
def call_llm(provider, model, messages, tools):
    if provider == "mock":
        return MOCK_RESPONSES.pop(0)          # a module-level global
    elif provider == "openrouter":
        client = OpenAI(base_url=..., api_key=...)   # rebuilt on every call
        # ...forty lines translating messages to OpenAI's format, inline...
    elif provider == "anthropic":
        client = anthropic.Anthropic()        # rebuilt on every call
        # ...fifty lines translating messages to Anthropic's format, inline...
```

Its docstring listed what should bother a reader: every new provider means editing this function; clients
are rebuilt on every call; translation can't be tested without a network; the mock reads a global that
tests must remember to clear. The point wasn't to fix any of it yet. It was to **feel it first**, so that
the fix in chapter 2 would be an answer to a real problem rather than a pattern applied for its own sake.

## First contact with real models

Both providers worked on the first live run, and the differences were already interesting. Asked
*"What is (17 × 23) + 4?"*, DeepSeek called `multiply` and then did the `+ 4` in its head. Claude called
`multiply` and *then* `add`, one extra round trip. Whether a model actually uses its tools varies a lot,
which is one reason a harness wants to make swapping models trivial. DeepSeek also wrote its answer in
LaTeX (`\(17 \times 23\)`), a small thing that chapter 4 fixed with a better system prompt.

There was also a lesson about Anthropic's API that would echo through the whole project. Modern Claude
models return *thinking blocks*, and those must be sent back **unchanged** on the next turn. Our neutral
`Message` type couldn't represent them, so it got a field called `raw` that holds the provider's original
content. It worked, and it was a crack in the abstraction from day one. That crack has a name in
`DECISIONS.md` (D8), and it's still open at the end of the book.

## Environment notes

Two small things from this stage are worth keeping. First, `uv` became the only Python tool: `uv sync`,
`uv run`, `uv add`, never `pip`, with uv managing the interpreter itself
(`python-preference = "only-managed"`). Second, an early attempt at authentication taught a subtle trap:
an *empty* `ANTHROPIC_API_KEY=` line in `.env` silently overrides other credential sources, because empty
still counts as "set".

## The one thing to remember

**Make the problem visible before you solve it.** A deliberately naive first version, with its smells
written down, turns every later pattern into an answer instead of a decoration.

## Questions to think about

- Template Method varies behavior through inheritance. What happens when two independent things need to
  vary, say, the provider *and* the logging?
- Which of the smells listed in `call_llm`'s docstring would you have noticed without the list?
