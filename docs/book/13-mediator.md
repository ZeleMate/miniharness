# Chapter 13. A team that talks through a coordinator

*Pattern: Mediator. Code: `src/miniharness/team.py`.*

## Trees only point down

Chapter 12's tree lets a parent *own* and call its children. But some multi-agent shapes are between
equals: a writer and a reviewer going back and forth, or agents handing work to one another. Wiring peers
directly to each other means every agent knows every other one, and changing who talks to whom means
editing the agents.

A Mediator moves the routing out of the participants. Objects stop talking to each other directly and
talk only through one coordinator that owns the rules. The chapter opened with an honest caveat: nothing in
the project *forced* this yet, the way the broken provider forced the circuit breaker. You chose to build it
anyway, as a real multi-agent shape that trees can't express (D133).

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

You chose two more things: each member sees *only* the messages addressed to it (D134), which keeps
contexts small and roles clean; and members keep their conversation between turns (D135), which needed a
new `Agent.follow_up()` to continue a finished run with another message.

Mechanically, the team adds its tools by *wrapping* each member's tools, on copies of the agents (D137).
That's a Decorator over the `ToolSet` interface, and your original agents are never modified. The allowed
recipients appear in the tool's schema *and* are checked in code (D138): the schema steers the model, and
the check enforces the rule.

## Three live runs, three lessons

This chapter's design was shaped more by live runs than by planning.

**Run one** went too well. The reviewer approved the first draft immediately, so the revision loop never
ran. It worked, but it proved nothing.

**Run two** asked for a bakery slogan of *exactly seven words* without the word "bread". The writer's
draft had six words. The reviewer didn't send feedback. It called `finish` with **its own, much longer
slogan**, which broke the rules too and wasn't the writer's work at all. The prompt had said "call finish
with the final text", and the model simply rewrote it. You chose to change the API (D136): `finish(result)`
became `approve()`, which takes no text. The team's result is always the last message the finisher
received. **When a role matters, enforce it in the API, not in the prompt.**

**Run three** exposed a consequence of isolation. The reviewer couldn't check "exactly seven words",
because it had never seen the task. An attempt to make the writer forward the requirements put them
*inside* the approved result. The real fix was to recognize whose job it is: sharing the brief is
coordination, and coordination is the mediator's job. The team now gives every member the original task
with their first message (D142), while keeping messages private.

The final run showed the full loop: draft, feedback ("8 words, please make it exactly 7"), revision,
approval. One telling detail: the first draft *was* seven words; the reviewer miscounted. In another run, a
reviewer approved a six-word slogan. **Models can't be trusted to count**, so rules that code can check
belong in code (D143). Validators on `approve()` are the logged but unbuilt next step.

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

**Every time a prompt failed to enforce a role, the fix was moving that rule into the mediator's API.** A
model will eventually do whatever the interface allows; make the wrong thing impossible.

## Questions to think about

- Add an `editor` between writer and reviewer by editing only `routes`. Did any agent need to change?
- Which of your own multi-agent rules live only in prompts? What would enforcing them in code look like?
