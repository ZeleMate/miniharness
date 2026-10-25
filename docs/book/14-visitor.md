# Chapter 14. Asking questions of a finished run

*Pattern: [Visitor](https://refactoring.guru/design-patterns/visitor). Code: `src/miniharness/trace.py`.*

## A tree waiting to be walked

Chapter 10 wrote every event to a JSONL file, and chapter 12 tagged each one with the agent and its depth.
Together they describe a tree: a run contains model calls and tool calls; a tool call that started a
sub-agent contains that sub-agent's run; team messages sit between member turns. What was missing was a
way to ask questions of that tree. Which agent spent the money? What did each tool return? Can I see it
as a report?

Each of those is a different *operation* over the same nodes. Putting every operation on every node class
(a `cost()` method, an `html()` method, a `to_json()` method) would bloat the nodes with unrelated concerns.
Visitor separates the operations from the structure.

## Rebuilding the tree

First, the flat event stream had to become a tree again, and that was the trickiest part of the stage.
Events arrive in **post-order** (chapter 12's D132): a sub-agent's whole run is reported *before* the tool
call that started it finishes. So the builder holds each nested run as "pending" until its parent's tool
call arrives, then attaches it there (D148).

That works because tools run one at a time. With concurrent tools, two sub-runs and two tool calls could
interleave and pair up wrongly. Robust pairing would need each nested run to carry the id of the tool call
that started it. It's another decision that quietly depends on D39.

The builder reads the *saved records* (the JSONL format), not live event objects (D147). One input format
covers files and, later, live streams. The consequence: the tracer's field names are now a contract, and
renaming one breaks old traces.

## Double dispatch

You chose GoF's classic form (D145). Each node has one method:

```python
class ToolCallNode:
    def accept(self, visitor):
        return visitor.visit_tool(self)
```

and each operation is a visitor class that overrides the visits it cares about:

```python
class CostSummary(TraceVisitor):
    def visit_model(self, node):
        self._stats(node.agent).cost_usd += node.cost_usd
```

This is *double dispatch*: the code that runs depends on two types, the node's (through `accept`) and the
visitor's (through the method it defines). The base visitor walks child nodes by default, so a visitor only
overrides what it needs (D151). The risk is that an override that forgets to call `super()` silently skips
part of the tree, for example missing a sub-agent's costs.

You chose two visitors: a **cost summary** per agent (calls, tokens, cost, tool calls, denials, time) and
an **HTML report** with collapsible runs. They compose: the report runs a cost summary for each run, so
each header shows its cost including its sub-agents (D153). Everything that reaches the HTML is escaped,
because tool output is untrusted: a file containing `<script>` must not run when you open the report
(D154).

## The expression problem

Visitor has a famous trade-off, sometimes called the *expression problem* (D145):

- **New operations are cheap.** One new visitor class, and no node changes.
- **New node types are expensive.** The base visitor and every visitor that cares must learn about them.

Plain methods on nodes are the exact opposite. So the choice depends on which side will grow. Here, the
node types (runs, model calls, tool calls, messages) were stable, and the operations were the open-ended
part. That made Visitor the right fit.

## The trace that caught a hallucination

The live check produced the best demonstration of the whole chapter. A delegated run was asked how many
action items were in a notes file that had **two**. The answer listed **four**, including "setting up the
docs portal" and "QA-ing the new login page", neither of which existed.

Without the tree, you couldn't tell which layer was wrong: the file, the sub-agent or the parent. A
five-line throwaway visitor, written on the spot without touching a single node class, walked the trace and
printed each tool's output:

- `read_file` returned the two real items.
- The researcher sub-agent reported exactly those two.
- The **parent** invented the other two in its final answer.

That's the pattern's promise in action: a new question, answered by a new visitor, in minutes (D146).

## The one thing to remember

**Visitor makes new operations cheap and new node types expensive.** Choose it when the questions keep
coming and the structure stays put.

## Questions to think about

- Write a `SlowestCalls` visitor that lists the three slowest model calls with their agent. Did you touch
  any node class?
- Think of a tree in your own work. Which side grows faster, the operations or the node types?
