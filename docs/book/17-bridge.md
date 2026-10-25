# Chapter 17. Two hierarchies that grow apart

*Pattern: [Bridge](https://refactoring.guru/design-patterns/bridge). Code: `src/miniharness/agent_types.py`.*

## A promise from stage 2

Back in chapter 2, the pattern journal (`PATTERNS.md`) promised that "a `ReActAgent` and a `PlannerAgent`
can each use any provider." Fifteen stages later, there was still only one agent class. Meanwhile the provider side had grown
into a whole hierarchy: three providers and seven wrappers. Adding agent types naively, an
`OpenRouterPlanner` and an `AnthropicPlanner` and so on, is exactly the N × M class explosion Bridge exists to
prevent.

## An honest starting point

The chapter began with an admission. `Agent` already held a `Provider` by composition, so in *shape* the
code was already a Bridge. But in *intent* it was chapter 2's Strategy: one context class swapping one
algorithm. A Bridge needs **two hierarchies that both grow**, joined by composition so they can grow
independently. Without a second agent type, there was no Bridge, only a Strategy (D198).

## The abstraction side grows

You chose two new agent types (D188), each varying a *different end* of the loop:

- **`PlannerAgent`:** before acting, one call without tools asks for a short numbered plan, and the plan
  stays in the conversation for every later step.
- **`ReviewerAgent`:** after the first answer of each turn, the draft is sent back for one review round
  before it's final.

A ReAct agent was considered and rejected: with native tool calling, ReAct is mostly a prompt, and a
text-parsing ReAct agent would re-implement what the adapters already do.

In Bridge terms, `Agent` is the *abstraction*, `PlannerAgent` and `ReviewerAgent` are *refined
abstractions*, the `Provider` protocol is the *implementor*, and OpenRouter, Anthropic, Mock and every
wrapper are *concrete implementors*.

## How they plug in

You chose to extend the loop with two new Template Method hooks and a new lifecycle state (D189):

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

Making planning a *state* rather than an extra call hidden inside a hook paid off immediately. As a state,
planning is a step like any other: it streams, it's traced, it emits cost events and it checkpoints. Done
inside `initial_messages()`, it would have run before the run officially started, never streamed, and been
missing from the trace's cost summary.

Composition (`Agent(provider, style=Planner())`) was considered too, and rejected for now. It would win if
agent types needed combining, such as a planner that also reviews. That's logged as the trigger to revisit.

## The test of a Bridge

Here's the pattern's whole promise, and the stage's most important result: **the provider side needed no
new code** (D190). Not one line. Every concrete implementor, wrappers included, worked with the new agent
types unchanged. A parametrized test runs 3 agent types × 4 providers. Three agent types and any number of
providers take 3 + N classes, not 3 × N.

You also chose how the facade exposes it (D191): `Harness("anthropic", agent_type=PlannerAgent)`. The class
itself is the factory. A string registry (`agent="planner"`) would have mirrored `create_provider`, but it
would have added a second global registry right before the stage about removing them. Strings belong at the
edge, in the example's command-line flags.

## Small decisions

- Every state that calls the model goes through one `model_call()` helper (D192), so no new state can
  forget to count the call or emit its cost event, the Bridge's "abstraction operations written in terms of
  implementor primitives".
- The planning call gets no tools, so the model can't act while planning, and the request lists the tools
  by name so it can still plan with them (D194).
- Whether a turn was already reviewed is read from the conversation itself (D196), so checkpoints and forks
  need no extra state.

## What the live runs showed

The same task cost 2, 3 and 4 model calls ($0.00045, $0.00062 and $0.00095) as plain, planner and reviewer.
Planning and reviewing don't pay off for trivial tasks.

And one lesson about self-review (D197): asked for Canberra's population, DeepSeek drafted a number, was
asked to check its unverified claims, couldn't (it had no tool for that), and kept the number with only a
hedge added. **A model reviewing itself shares its own blind spots.** A critic on a *different* provider
would need a second implementor reference, an easy extension the Bridge makes possible but this stage
didn't build.

## Bridge vs Strategy vs Adapter

- **Bridge vs Strategy:** the same code shape. Strategy is *one* context swapping *one* algorithm. Bridge is
  *two* hierarchies that both grow. The test: writing `PlannerAgent` added nothing to the provider side.
- **Bridge vs Adapter:** an Adapter makes *existing* incompatible interfaces fit, after the fact. A Bridge is
  designed *up front* so that the two sides never need fitting. Here they meet: the adapters live inside the
  concrete implementors.

## The one thing to remember

**A Bridge is real when you can grow one side without touching the other.** The proof here was a whole new
agent type with zero lines changed on the provider side.

## Questions to think about

- Write a `ConfirmingAgent` that asks a human whether an answer is good enough. Did you touch `providers/`?
- Would `PlannerReviewerAgent(PlannerAgent, ReviewerAgent)` compose the two hooks correctly? When would
  composition have been the better design?
