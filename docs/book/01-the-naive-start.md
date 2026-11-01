# Chapter 1. The naive start: a loop and an ugly function

*Pattern: [Template Method](https://refactoring.guru/design-patterns/template-method). Code: `src/miniharness/agent.py`.*

## The smallest thing that works

Every agent harness, however sophisticated, has the same loop at its heart:

1. Send the conversation to the model.
2. If the model asked for tools, run them, add their results to the conversation, and go back to 1.
3. Otherwise, the model's reply is the answer.

The first scaffold is exactly that loop, plus a handful of neutral data types the rest of the code speaks:
a `Message` (a role, some text, maybe tool calls), a `ToolCall` (an id, a name, arguments), and an
`LLMResponse` (the assistant's message plus *why* it stopped: finished, wants tools, ran out of tokens).
Three tools to start with: `add`, `multiply` and `current_time`. And a `MockProvider` that replays scripted
replies, so the loop can be tested without a network or an API key.

## Template Method: a fixed skeleton with replaceable steps

The loop's *structure* is fixed, but each step is a method a subclass can override:

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

This is one of the oldest tools in object-oriented design, and it has a well-known limit: inheritance gives
you **one axis of variation per subclass**. A `LoggingAgent` and a `PoliteAgent` can't be combined without a
third class. That limit is why the next chapter reaches for composition instead.

The hooks are durable, though. The Bridge chapter adds two more (`first_state` and `after_answer`) to build
new kinds of agents, and the lifecycle states of chapter 9 call these same hooks, so subclasses keep working
through every later refactor.

## The deliberately ugly part

The provider code starts out bad *on purpose*. One function does everything:

```python
def call_llm(provider, model, messages, tools):
    if provider == "mock":
        return MOCK_RESPONSES.pop(0)  # a module-level global
    elif provider == "openrouter":
        client = OpenAI(base_url=..., api_key=...)  # rebuilt on every call
        # ...forty lines translating messages to OpenAI's format, inline...
    elif provider == "anthropic":
        client = anthropic.Anthropic()  # rebuilt on every call
        # ...fifty lines translating messages to Anthropic's format, inline...
```

Its smells are worth listing explicitly: every new provider means editing this function; clients are
rebuilt on every call; translation can't be tested without a network; the mock reads a global that tests
must remember to clear. None of this gets fixed yet. The point is to **see the problem first**, so that the
fix in chapter 2 answers a real problem rather than applying a pattern for its own sake.

## What real models add

Running the loop against real models shows variation that a mock hides. Asked *"What is (17 × 23) + 4?"*,
one model may call `multiply` and do the `+ 4` itself, while another calls `multiply` and *then* `add`, one
extra round trip. How much a model relies on its tools varies a lot, which is one reason a harness wants
swapping models to be trivial. Models also differ in output style (some answer in LaTeX, `\(17 \times
23\)`), which chapter 4's system prompt addresses.

Anthropic's API adds a constraint that runs through the whole design. Modern Claude models return
*thinking blocks*, and those must be sent back **unchanged** on the next turn. A neutral `Message` type
can't represent them, so it gets a field called `raw` that holds the provider's original content. It works,
and it's a crack in the abstraction from the start. That crack is D8 in `DECISIONS.md`, and it stays open
to the end of the book.

## Environment notes

Two practical points. First, `uv` is the only Python tool: `uv sync`, `uv run`, `uv add`, with uv managing
the interpreter itself (`python-preference = "only-managed"`). Second, an authentication trap: an
`ANTHROPIC_API_KEY` in the environment silently overrides an `ant auth login` profile, and the `ant` CLI
counts even an *empty* `ANTHROPIC_API_KEY=` line as "set". (The Python SDK treats an empty value as unset,
but tools differ, so `.env.example` leaves the line commented out.)

## The one thing to remember

**Make the problem visible before you solve it.** A deliberately naive first version, with its smells
written down, turns every later pattern into an answer instead of a decoration.

## Questions to think about

- Template Method varies behavior through inheritance. What happens when two independent things need to
  vary, say, the provider *and* the logging?
- Which of `call_llm`'s smells would you have noticed without the list?
