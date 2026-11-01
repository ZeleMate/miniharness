# Chapter 13. A team that talks through a coordinator

*Pattern: [Mediator](https://refactoring.guru/design-patterns/mediator). Code: `src/miniharness/team.py`.*

## Trees only point down

Chapter 12's tree lets a parent *own* and call its children. But some multi-agent shapes are between
equals: a writer and a reviewer going back and forth, or agents handing work to one another. Wiring peers
directly to each other means every agent knows every other one, and changing who talks to whom means
editing the agents.

A Mediator moves the routing out of the participants. Objects stop talking to each other directly and talk
only through one coordinator that owns the rules. Unlike the circuit breaker, nothing earlier in the build
forces this pattern; it's here because it covers a real multi-agent shape that trees can't express (D133).

## The team

```python
team = Team(
    members={"writer": writer, "reviewer": reviewer},
    routes={"writer": ["reviewer"], "reviewer": ["writer"]},
    finishers={"reviewer"},
)
result = team.run("writer", "Write a haiku about undo.")
```

Members never reference each other. Each gets a `send_message(to, text)` tool limited to the recipients its
route allows, and designated members get a tool to finish. The team delivers each message, runs that
member's turn, and collects whatever it sends next.

Two more rules: each member sees *only* the messages addressed to it (D134), which keeps contexts small and
roles clean; and members keep their conversation between turns (D135), through `Agent.follow_up()`, which
continues a finished run with another message.

Mechanically, the team adds its tools by *wrapping* each member's tools, on copies of the agents (D137).
That's a Decorator over the `ToolSet` interface, and the caller's agents are never modified. The allowed
recipients appear in the tool's schema *and* are checked in code (D138): the schema steers the model, and
the check enforces the rule.

## Three failure modes, three rules

**A reviewer that approves too fast proves nothing.** If the first draft is approved immediately, the
revision loop never runs. A demo task needs constraints a first draft is likely to miss (for example "a
slogan of *exactly seven words* without the word 'bread'").

**A reviewer can replace the work instead of judging it.** With a `finish(result)` tool and a prompt saying
"call finish with the final text", a reviewer can "approve" by passing **its own rewrite**, which may break
the rules and isn't the writer's work at all. The fix is in the API (D136): `finish(result)` becomes
`approve()`, which takes no text. The team's result is always the last message the finisher received.
**When a role matters, enforce it in the API, not in the prompt.**

**Isolation can starve a member of context.** A reviewer that has never seen the task can't check "exactly
seven words". Asking the writer to forward the requirements puts them *inside* the draft, which can then
become the approved result. The real fix is to recognize whose job it is: sharing the brief is
coordination, and coordination is the mediator's job. The team gives every member the original task with
their first message (D142), while keeping messages private.

A working loop then looks like: draft, feedback ("8 words, please make it exactly 7"), revision, approval.
But the feedback itself may be wrong: **models can't be trusted to count**. A reviewer can miscount a
correct draft or approve a wrong one. Rules that code can check belong in code (D143); validators on
`approve()` are the open next step.

## The rest of the design

- A member's turn ends when its own run finishes (D139), which costs one extra short model call per turn,
  as the model replies once more after sending. Ending the turn the moment it sends would halve the calls.
- Messages are delivered first in, first out (D140).
- The team ends on approval, a turn limit, a dead end (a member that neither sends nor approves), or a
  stopped member (D141). A budget stop ends the whole team at once, unlike chapter 12's trees.
- `MessageRouted` events show the conversation on the console as `── writer → reviewer: ...` (D144).

## Mediator vs Observer

Both decouple senders from receivers, so they're often confused. **Observer broadcasts**: whoever
subscribed hears, and the subject doesn't care who. **Mediator routes**: it knows every participant and the
rules between them, and it decides who hears what. Handoff and supervisor setups in multi-agent frameworks
are mediators: the routing lives outside the agents.

## The one thing to remember

**Each time a prompt fails to enforce a role, the fix is moving that rule into the mediator's API.** A model
will eventually do whatever the interface allows; make the wrong thing impossible.

## Questions to think about

- Add an `editor` between writer and reviewer by editing only `routes`. Did any agent need to change?
- Which of your own multi-agent rules live only in prompts? What would enforcing them in code look like?
