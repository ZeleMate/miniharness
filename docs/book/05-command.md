# Chapter 5. Actions you can take back

*Pattern: [Command](https://refactoring.guru/design-patterns/command). Code: `src/miniharness/tools/base.py`, `tools/toolbox.py`, `tools/files.py`.*

## What a tool call was

Until this stage, a tool call was a dictionary lookup followed by a function call. The result came back,
and that was the end of it. Nothing recorded what had happened, nothing could be replayed, and nothing
could be undone. The four tools also lived in a module-level `TOOLS` dict, another global.

The Command pattern starts from a simple observation: **you can't hold on to a function call, but you can
hold on to an object.** Turn each call into an object that carries its tool, its arguments, its result and
whatever is needed to reverse it, and logging, replay and undo all become possible.

## The roles

GoF names four roles, and each one has a concrete home here:

- **Command:** `ToolCommand`, one call packaged with everything needed to run, log or undo it.
- **Invoker:** `Toolbox`, which runs commands and keeps their history.
- **Receiver:** the workspace on disk, which is what actually changes.
- **Client:** the `Agent`, which turns the model's tool calls into commands.

## What undo should mean

The most interesting question was what "undo" means when most tools have no side effects. `add` changes
nothing; `current_time` changes nothing; but a file write does. Three answers were possible: every command
implements undo (as a no-op for read-only tools), only log and replay, or let tools *declare* their nature.
You chose declaration (D30):

```python
class Tool:
    side_effects = False   # read-only by default
    reversible = False

class WriteFile(Tool):
    side_effects = True
    reversible = True
```

Why not a no-op undo everywhere? Because it lies. A no-op `undo()` on "send email" would *look* like it
worked. The two flags separate three honest categories: changes nothing, changes something reversibly, and
changes something permanently.

## A tool worth undoing

To make undo real, the stage added `read_file` and `write_file`, confined to a workspace directory (D31).
The confinement detail matters: the path is *resolved* first, following `..` and symlinks, and only then
checked to be inside the workspace. Checking the raw string for `..` would miss a symlink pointing
outside. Tests cover `../escape.txt`, absolute paths and a malicious symlink.

## Five decisions worth studying

**Snapshot or compensation? (D33)** There are two ways to undo. A *snapshot* records the old state and
restores it: `write_file` remembers the file's previous contents, or that it didn't exist. A *compensating
command* runs the inverse action without recording state, the way you refund a payment rather than
"un-charging" it. Snapshots are exact and simple for files. Compensation is what you need when state can't
be captured, and it's the basis of the *Saga* pattern in distributed systems.

**Stop at what can't be undone (D34).** If the history holds a file write followed by a sent email,
`undo_last()` refuses to undo the write, because undoing it would leave the world inconsistent with an
email that already went out. Stopping is the safe default.

**Optimistic concurrency (D35).** Undo remembers what it *wrote* and refuses if the file has changed since.
Otherwise undo would silently destroy someone else's edit.

**Failures stay out of history (D36).** A failed call becomes error text the model can read and recover
from, and since it changed nothing, there's nothing to undo.

**Least privilege (D37).** `Agent(provider)` with no arguments gets only read-only tools. File access must
be granted deliberately, with an explicit workspace.

## The live run

Asked to write a haiku to a file and read it back, the model sent `write_file` and `read_file` **in the
same turn**. It worked only because the Toolbox ran them in order. Running them concurrently would have
raced. That observation became an open decision (D39) that comes back in several later chapters: the
harness assumes tools run one at a time, and more of the design quietly depends on it than you'd expect.

The `--rewind` flag then undid the write, and the workspace was empty again.

## The one thing to remember

**Turning a call into an object is what makes it possible to log, replay and undo it.** Claude Code's
rewind and checkpoints are this pattern applied to file edits.

## Questions to think about

- An `AppendFile` tool: what's its undo information? Is a snapshot or an inverse operation cheaper?
- Name an action in your own systems that is reversible only by compensation, never by snapshot.
