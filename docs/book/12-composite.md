# Chapter 12. Agents inside tools

*Pattern: [Composite](https://refactoring.guru/design-patterns/composite). Code: `src/miniharness/tools/agent_tool.py`.*

## Delegation without a new machine

Real harnesses delegate. A sub-agent tool sends a focused task to a fresh agent and gets back only a
summary, so the parent's context stays small. The question for this stage is how to add delegation without
building a second set of machinery for policies, events and undo.

Composite answers it. The pattern treats a single object and a group of objects through the same
interface, so you can build trees and run operations across them recursively. Applied here: **an agent that
is also a tool.**

## AgentTool

A sub-agent is an ordinary `Tool` subclass (D119):

```python
researcher = AgentTool(
    name="researcher",
    description="Reads files in the workspace and summarizes them.",
    prototype=Agent(cheap_provider, tools=ToolboxView.read_only(toolbox)),
)
toolbox.add(researcher)
```

To the parent, `researcher` is indistinguishable from `add`: a name, a description, a schema with a `task`
parameter, and a string result. Inside, its `run()` drives a whole agent with its own tools, which can
include more `AgentTool`s. That's a tree. And because it's just a tool, the Toolbox, the policy chain, the
events and the history all work unchanged. That uniformity *is* the pattern.

Each call runs a **fresh copy** of a prototype agent (D120), chapter 11's Prototype at work. Calls can't
influence each other, and the parent's context grows only by the final answer, which is the main reason
harnesses use sub-agents at all.

## The Composite operation

Every Composite has an operation that's computed over the tree. Here it's `side_effects` (D121):

- A sub-agent whose tools are all read-only counts as read-only.
- A sub-agent that can write has side effects.
- That propagates up any depth: a manager whose only side-effecting child is a writer has side effects.

This connects straight to chapter 7: the policy chain treats a whole subtree like a single tool. A
read-only researcher gets `AllowReadOnly` and runs without asking; a writing sub-agent needs approval.

When side effects can't be determined, through a cycle (an agent that contains itself) or tools that can't
be inspected, they're assumed to exist (D126). Fail closed again: a wrong "read-only" would skip approval.

## The attribution problem, and a ContextVar

A sub-agent's tool calls go through a Toolbox, often a view of the parent's, that doesn't know *which
agent* is calling it. Passing "agent name and depth" through every call explicitly would change
`execute()`, the `ToolSet` protocol and every wrapper.

The solution is Python's `contextvars` (D123). Each agent marks "I'm running" for the duration of its step,
and the event bus tags every event with the innermost running agent and its depth. A sub-agent runs
*inside* its parent's tool call, so the innermost scope is always the agent doing the work. Nested agents
get depth 1, 2, and so on, with no extra wiring.

It's implicit context instead of explicit parameters, and that's a real trade-off. It works, and
ContextVars are safe with threads and asyncio, unlike a global. But nothing in `Toolbox.execute()` tells a
reader that attribution happens. Chapter 18 explains why this module-level object is fine while the
provider registry isn't.

## Smaller decisions

- A depth limit (default 3) stops an agent that can call itself from recursing until the budget or the
  stack runs out (D128). Past the limit, the model gets an error instead.
- Sub-agent copies share the provider, so one usage tracker counts every model call in the tree, and one
  budget covers it (D129).
- `Toolbox.add()` is public (D130), so a sub-agent can get a view of the Toolbox that will contain it.
- When a sub-agent stops on the budget, the parent receives "[stopped: budget]" as an ordinary tool result
  and carries on (D131). Arguably a budget stop should end the whole tree at once; it's open.
- Nested events arrive with the inner calls first (D132): a sub-agent's run finishes before the parent's
  tool call does. Rebuilding the tree from a trace needs both depth and order, which chapter 14 handles.

## What a delegated run looks like

With `--delegate`, the researcher's work appears *indented* under the parent in the console: its own model
calls and its `read_file`. The parent gets only the answer, and the policy auto-allows the researcher
because its derived side effects are `False`.

## The one thing to remember

**When a group can behave like a single item, everything built for single items works on groups for
free.** Policies, events and undo need no changes for sub-agents, because a sub-agent is just a tool.

## Questions to think about

- Give the researcher its own cheaper model. Where does its cost appear now, and does the shared budget
  still apply?
- When is implicit context (a ContextVar) better than an explicit parameter, and when is it worse?
