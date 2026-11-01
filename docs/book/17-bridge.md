# Chapter 17. Two hierarchies that grow apart

*Pattern: [Bridge](https://refactoring.guru/design-patterns/bridge). Code: `src/miniharness/agent_types.py`.*

## A claim from stage 2

Chapter 2 claims that "a `ReActAgent` and a `PlannerAgent` can each use any provider." Until this stage,
though, there's only one agent class, while the provider side has grown into a whole hierarchy: three
providers and seven wrappers. Adding agent types naively, an `OpenRouterPlanner` and an `AnthropicPlanner`
and so on, is exactly the N × M class explosion Bridge exists to prevent.

## Shape is not intent

`Agent` already holds a `Provider` by composition, so in *shape* the code is already a Bridge. But in
*intent* it's chapter 2's Strategy: one context class swapping one algorithm. A Bridge needs **two
hierarchies that both grow**, joined by composition so they can grow independently. Without a second agent
type, there's no Bridge, only a Strategy (D198).

## The abstraction side grows

Two new agent types (D188) each vary a *different end* of the loop:

- **`PlannerAgent`:** before acting, one call without tools asks for a short numbered plan, and the plan
  stays in the conversation for every later step.
- **`ReviewerAgent`:** after the first answer of each turn, the draft is sent back for one review round
  before it's final.

A ReAct agent isn't one of them: with native tool calling, ReAct is mostly a prompt, and a text-parsing ReAct
agent would re-implement what the adapters already do.

In Bridge terms, `Agent` is the *abstraction*, `PlannerAgent` and `ReviewerAgent` are *refined
abstractions*, the `Provider` protocol is the *implementor*, and OpenRouter, Anthropic, Mock and every
wrapper are *concrete implementors*.

## How they plug in

The loop gains two new Template Method hooks and a new lifecycle state (D189):

```python
class PlannerAgent(Agent):
    def first_state(self):  # start by planning instead of thinking
        return Planning()


class ReviewerAgent(Agent):
    def after_answer(self, response):
        if not self._reviewed_this_turn():
            self.messages.append(Message(role="user", content=self.review_request))
            return Thinking()  # one more pass of the normal loop
        return super().after_answer(response)
```

Making planning a *state* rather than an extra call hidden inside a hook matters. As a state, planning is a
step like any other: it streams, it's traced, it emits cost events and it checkpoints. Done inside
`initial_messages()`, it would run before the run officially starts, never stream, and be missing from the
trace's cost summary.

Composition (`Agent(provider, style=Planner())`) is the alternative. It would win if agent types needed
combining, such as a planner that also reviews; that's the recorded trigger to revisit.

## The test of a Bridge

Here's the pattern's whole promise: **the provider side needs no new code** (D190). Every concrete
implementor, wrappers included, works with the new agent types unchanged. A parametrized test runs 3 agent
types × 4 providers. Three agent types and any number of providers take 3 + N classes, not 3 × N.

The facade exposes it as `Harness("anthropic", agent_type=PlannerAgent)` (D191). The class itself is the
factory. A string registry (`agent="planner"`) would mirror `create_provider`, but it would add a second
global registry right before the stage about removing them. Strings belong at the edge, in the example's
command-line flags.

## Smaller decisions

- Every state that calls the model goes through one `model_call()` helper (D192), so no new state can forget
  to count the call or emit its cost event: the Bridge's "abstraction operations written in terms of
  implementor primitives".
- The planning call gets no tools, so the model can't act while planning, and the request lists the tools by
  name so it can still plan with them (D194).
- Whether a turn was already reviewed is read from the conversation itself (D196), so checkpoints and forks
  need no extra state.

## Costs and limits

Each refined abstraction adds model calls: a simple tool task takes about 2, 3 and 4 calls as plain,
planner and reviewer. Planning and reviewing don't pay off for trivial tasks.

Self-review has a hard limit (D197). Asked to verify a factual claim with no tool to check it, a model can
only hedge, not correct. **A model reviewing itself shares its own blind spots.** A critic on a *different*
provider would need a second implementor reference, an easy extension the Bridge makes possible and the code
doesn't build.

## Bridge vs Strategy vs Adapter

- **Bridge vs Strategy:** the same code shape. Strategy is *one* context swapping *one* algorithm. Bridge is
  *two* hierarchies that both grow. The test: writing `PlannerAgent` adds nothing to the provider side.
- **Bridge vs Adapter:** an Adapter makes *existing* incompatible interfaces fit, after the fact. A Bridge is
  designed *up front* so that the two sides never need fitting. Here they meet: the adapters live inside the
  concrete implementors.

## The one thing to remember

**A Bridge is real when you can grow one side without touching the other.** The proof here is a whole new
agent type with zero lines changed on the provider side.

## Questions to think about

- Write a `ConfirmingAgent` that asks a human whether an answer is good enough. Did you touch `providers/`?
- Would `PlannerReviewerAgent(PlannerAgent, ReviewerAgent)` compose the two hooks correctly? When would
  composition have been the better design?
