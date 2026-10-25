# Chapter 2. Two providers, one interface

*Patterns: Strategy and Adapter. Code: `src/miniharness/providers/`, `src/miniharness/adapters/`.*

## The safety net first

Before touching `call_llm`, we wrote tests that pinned down its exact behavior: for a conversation with a
system prompt, a user message, an assistant turn with two tool calls and two tool results, *precisely*
what JSON goes to OpenRouter and what goes to Anthropic, and precisely how each response is parsed back.
The tests used fake SDK clients, small objects that record the request and return a canned response, so
they ran offline and instantly.

These are called **characterization tests**: they describe what the code *does*, not what it *should* do.
That distinction matters. Their job isn't to prove the code right; it's to guarantee that a refactor
doesn't change behavior by accident. Through everything that followed, those payload assertions never
changed (D1).

## Strategy: the "which model?" decision becomes an object

The first design question was how to express "a thing that can turn a conversation into a reply." Three
options were on the table: a `typing.Protocol`, an abstract base class, or a plain function. You chose the
Protocol (D2):

```python
class Provider(Protocol):
    model: str
    def complete(self, messages: list[Message], tools: dict[str, ToolSpec]) -> LLMResponse: ...
```

A Protocol is *structural*: any class with a matching `complete()` method qualifies, whether or not it
inherits from anything. That made every test double trivially valid, and later it let wrappers, proxies
and mocks stand in for providers everywhere without ceremony. The cost is that a missing method only fails
when it's called, not when the object is created, as it would with an abstract base class.

The Agent then received a provider from outside, instead of a string (D4):

```python
agent = Agent(provider=OpenRouterProvider(model="deepseek/deepseek-chat"))
```

That's the **Strategy** pattern: the algorithm for one step ("ask a model") is an object the caller picks,
and the Agent never asks which one it got. Compare it with chapter 1's Template Method. Both let one step
vary, but Template Method varies it by *inheritance* and Strategy by *composition*. Composition wins here
because which model answers has nothing to do with what kind of agent is asking. A planning agent and a
reviewing agent should each be able to use any model, which is exactly the point the Bridge chapter
returns to.

## Adapter: one conversation, two dialects

The harder half was translation. OpenAI's chat format and Anthropic's Messages format describe the same
things very differently:

| | OpenAI / OpenRouter | Anthropic |
|---|---|---|
| System prompt | a message with `role: "system"` | a separate `system=` parameter |
| Tool calls | `message.tool_calls[]` with JSON-string arguments | `tool_use` content blocks with object arguments |
| Tool results | messages with `role: "tool"` | `tool_result` blocks inside a **user** message |

Anthropic adds a subtle rule: all the results for one assistant turn must share a *single* user message.

The design question was where translation should live. You chose separate adapter objects (D3):
`OpenAIChatAdapter` and `AnthropicMessagesAdapter`, each with a `to_wire()` and a `from_wire()`, pure
functions with no network. A provider composes an adapter with an SDK client:

```python
class OpenRouterProvider:
    def complete(self, messages, tools):
        request = self.adapter.to_wire(messages, tools)
        response = self.client.chat.completions.create(model=self.model, **request)
        return self.adapter.from_wire(response)
```

This separates two different reasons for change. The *format* changes when an API's message shape
changes; the *transport and configuration* change when you switch endpoints or keys. Kept apart, the
OpenAI adapter can be reused for any OpenAI-compatible server (Ollama, vLLM) without subclassing anything.

## The decisions nobody asked about

Several small choices were made while implementing, and listing them afterwards became the project's
habit:

- SDK clients became injectable, `Provider(model, client=None)`: tests pass a fake, and real use stays
  one line. The default quietly depends on environment variables, which is a hidden dependency (D5).
- The adapter builds the *format*, and the provider adds `model` and `max_tokens`, because those are
  configuration, not format (D7).
- `call_llm` was simply deleted rather than kept as a compatibility shim. Shims protect a library's
  users, and this project had none (D9).
- And the `raw` field stayed. It's where the abstraction leaks: if you switched providers in the middle of
  a conversation, OpenRouter would silently ignore Anthropic's raw content (D8).

## Every adapter leaks somewhere

That last point deserves its own heading. An adapter promises a common interface over different systems,
and eventually every adapter meets something the common interface can't express. Here it was Anthropic's
thinking blocks, which must be replayed byte for byte. We could have hidden that, by dropping the blocks
and losing the model's earlier reasoning, or broken the abstraction with a provider-specific field. We
chose the honest leak and wrote it down. Knowing *where* your abstraction leaks is better than pretending
it doesn't.

## The one thing to remember

**Lock down behavior before you change structure.** Characterization tests turned a scary refactor into
a safe one: the structure changed completely, and the tests proved the bytes on the wire didn't.

## Questions to think about

- The Protocol let a mock be a provider without inheriting anything. What did we give up compared with an
  abstract base class?
- Where does your own code translate between two formats inline? What would pulling that into an adapter
  make testable?
