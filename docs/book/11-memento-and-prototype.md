# Chapter 11. Going back in time

*Patterns: Memento and Prototype. Code: `src/miniharness/checkpoint.py`, `Agent.checkpoint()`, `restore()`,
`fork()`.*

## Three things the harness couldn't do

By this point the harness could run, watch and protect an agent, but it couldn't go back. It couldn't
*rewind* a conversation (and the files it had changed), *resume* a run that stopped on a budget or a crash,
or *fork* a run to try an alternative from the same point. Claude Code's rewind feature, which restores the
conversation and the code together, is the closest real-world example of what we were after.

Two patterns cover this:

- **Memento:** capture an object's state as a snapshot you can restore later, without exposing the
  object's internals to whoever holds the snapshot.
- **Prototype:** create new objects by copying a configured one instead of building them from scratch.

You asked for all four capabilities: rewind the conversation, rewind file changes too, save to disk and
resume, and fork (D105).

## The memento

`agent.checkpoint()` returns a `Checkpoint`: a deep copy of the messages, the lifecycle state, the
model-call count, and a marker for the position in the Toolbox's history. `agent.restore(checkpoint)` puts
everything back.

The roles map neatly. The **originator** is the Agent, which creates and restores checkpoints. The
**memento** is the `Checkpoint`. The **caretaker** is whoever holds it: a test, you, or an autosave
observer.

GoF's memento is *opaque*: only the originator can read it. Ours is a readable frozen dataclass (D108),
because saving it as JSON needs the fields, and Python can't enforce privacy anyway. The intent survives
as a convention: only the Agent builds and restores them.

The copying is deliberate in both directions (D109). Capturing copies, so later changes to the agent
don't alter the checkpoint. Restoring copies too, so changes after restoring don't alter it either, and the
same checkpoint can be restored any number of times. Both are tested.

## Rewinding the files too

Here two patterns combine. The conversation comes back from the memento; the files come back through
chapter 5's command history. The checkpoint remembers the Toolbox's history position, and restoring undoes
every change made after it.

Restoring is all-or-nothing for irreversible actions (D112). The Toolbox scans the range *before* undoing
anything: if an irreversible action like a sent email is in the way, nothing changes, neither files nor
conversation. One honest gap remains. An individual undo can still fail halfway (if a file was edited by
someone else since, chapter 5's optimistic-concurrency check refuses), leaving earlier undos already done.
True all-or-nothing would need a transaction log.

Undone commands stay in the history, marked as undone (D113). "Written, then rewound" is a more truthful
audit log than silently deleting the record.

## Saving, resuming, and their limits

Checkpoints save to JSON atomically (write a temporary file, then rename, so a crash can never leave half a
checkpoint) and carry a format version (D114). Each lifecycle state knows how to save and rebuild itself
(D110), which is what makes resuming *mid-run* possible, even with tool calls still pending.

You chose JSON for Anthropic's raw content too, converting the SDK's objects with `model_dump()` (D106).
That's tested offline with real Anthropic SDK block objects, but it was never confirmed against the real
API, because the Anthropic key had stopped working by then. The book flags it the way the decision log
does: **unverified live**.

Two limits are worth understanding. File rewind only works within one process: the command history lives
in memory, so a checkpoint loaded from disk can restore the conversation but not undo files. Each Toolbox
has a random id, and a checkpoint from another Toolbox restores the conversation only, with a warning,
rather than undoing the wrong things (D111). And resuming re-runs pending tool calls (D117): if a process
crashes *while* a tool runs, resuming runs it again. That's *at-least-once* execution; exactly-once would
need a record written before and after every tool call.

## The live run

A run with a tiny budget stopped after one model call. The autosave held it in the `thinking` state. A
rerun with the same checkpoint file resumed in a new process, skipped the first model call, finished with
the next tool call, and deleted the file. The autosave itself was an *observer* subscribed to state
changes (D116), with no Agent changes at all: Observer driving Memento.

## Prototype: copies that keep their type

`agent.fork(checkpoint, provider=other)` copies an agent and lets the copy continue independently from a
checkpoint. It's implemented with `copy.copy(self)`, and that's Prototype's real advantage over calling a
constructor (D115): **a fork of a subclass is that subclass.** The caller doesn't need to know the
original's concrete class or its configuration.

You chose to copy the conversation but share everything else unless it's overridden (D107), and the fork
warns when it shares the original's Toolbox, since two agents writing into one workspace and one undo
history will interfere. Sharing the provider means sharing its usage tracker, so a fork's spending counts
against the same budget, which is usually what you want.

## The one thing to remember

**Rewind is two patterns working together.** Memento restores the conversation, Command undoes the files.
Neither alone could do what Claude Code's rewind does.

## Questions to think about

- Take a checkpoint, fork it onto two different models, and compare their answers and costs. What does
  the fork share that it shouldn't?
- What would you need to make tool execution exactly-once across crashes?
