# Chapter 11. Going back in time

*Patterns: [Memento](https://refactoring.guru/design-patterns/memento) and [Prototype](https://refactoring.guru/design-patterns/prototype). Code: `src/miniharness/checkpoint.py`, `Agent.checkpoint()`, `restore()`,
`fork()`.*

## Three things the harness can't do yet

By this point the harness can run, watch and protect an agent, but it can't go back. It can't *rewind* a
conversation (and the files it changed), *resume* a run that stopped on a budget or a crash, or *fork* a run
to try an alternative from the same point. The rewind feature in coding agents, which restores the
conversation and the code together, is the closest real-world example.

Two patterns cover this:

- **Memento:** capture an object's state as a snapshot you can restore later, without exposing the object's
  internals to whoever holds the snapshot.
- **Prototype:** create new objects by copying a configured one instead of building them from scratch.

This stage supports all four capabilities: rewind the conversation, rewind file changes too, save to disk
and resume, and fork (D105).

## The memento

`agent.checkpoint()` returns a `Checkpoint`: a deep copy of the messages, the lifecycle state, the
model-call count, and a marker for the position in the Toolbox's history. `agent.restore(checkpoint)` puts
everything back.

The roles map neatly. The **originator** is the Agent, which creates and restores checkpoints. The
**memento** is the `Checkpoint`. The **caretaker** is whoever holds it: a test, a caller, or an autosave
observer.

GoF's memento is *opaque*: only the originator can read it. This one is a readable frozen dataclass (D108),
because saving it as JSON needs the fields, and Python can't enforce privacy anyway. The intent survives as
a convention: only the Agent builds and restores them.

The copying is deliberate in both directions (D109). Capturing copies, so later changes to the agent don't
alter the checkpoint. Restoring copies too, so changes after restoring don't alter it either, and the same
checkpoint can be restored any number of times. Both are tested.

## Rewinding the files too

Here two patterns combine. The conversation comes back from the memento; the files come back through
chapter 5's command history. The checkpoint remembers the Toolbox's history position, and restoring undoes
every change made after it.

Restoring is all-or-nothing for irreversible actions (D112). The Toolbox scans the range *before* undoing
anything: if an irreversible action like a sent email is in the way, nothing changes, neither files nor
conversation. One gap remains. An individual undo can still fail halfway (if a file was edited by someone
else since, chapter 5's optimistic-concurrency check refuses), leaving earlier undos already done. True
all-or-nothing would need a transaction log.

Undone commands stay in the history, marked as undone (D113). "Written, then rewound" is a more truthful
audit log than silently deleting the record.

## Saving, resuming, and their limits

Checkpoints save to JSON atomically (write a temporary file, then rename, so a crash can never leave half a
checkpoint) and carry a format version (D114). Each lifecycle state knows how to save and rebuild itself
(D110), which is what makes resuming *mid-run* possible, even with tool calls still pending.

Anthropic's raw content is stored as JSON too, converting the SDK's objects with `model_dump()` (D106).
That's tested offline with real Anthropic SDK block objects but not against the real API, so D106 is marked
unverified.

Two limits are worth understanding. File rewind only works within one process: the command history lives
in memory, so a checkpoint loaded from disk can restore the conversation but not undo files. Each Toolbox
has a random id, and a checkpoint from another Toolbox restores the conversation only, with a warning,
rather than undoing the wrong things (D111). And resuming re-runs pending tool calls (D117): if a process
crashes *while* a tool runs, resuming runs it again. That's *at-least-once* execution; exactly-once would
need a record written before and after every tool call.

## Autosave as an observer

The example's autosave is an *observer* subscribed to state changes (D116), with no Agent changes at all:
Observer driving Memento. A run with a tiny budget stops after one model call and keeps its checkpoint;
rerunning with the same file resumes in a new process without repeating that call, finishes, and deletes
the file.

## Prototype: copies that keep their type

`agent.fork(checkpoint, provider=other)` copies an agent and lets the copy continue independently from a
checkpoint. It's implemented with `copy.copy(self)`, and that's Prototype's real advantage over calling a
constructor (D115): **a fork of a subclass is that subclass.** The caller doesn't need to know the
original's concrete class or its configuration.

A fork copies the conversation but shares everything else unless it's overridden (D107), and it warns when
it shares the original's Toolbox, since two agents writing into one workspace and one undo history will
interfere. Sharing the provider means sharing its usage tracker, so a fork's spending counts against the
same budget, which is usually what you want.

## The one thing to remember

**Rewind is two patterns working together.** Memento restores the conversation, Command undoes the files.
Neither alone can restore both.

## Questions to think about

- Take a checkpoint, fork it onto two different models, and compare their answers and costs. What does the
  fork share that it shouldn't?
- What would you need to make tool execution exactly-once across crashes?
