# Epilogue: what it all adds up to

Eighteen stages, 214 decisions, 321 tests. Looking back, the individual patterns matter less than the ideas
that kept coming back. This chapter collects those ideas, the bugs that taught the most, the environment
problems that cost real time, and the questions the project deliberately left open.

## Seven ideas that kept coming back

**1. Fail closed.** Whenever the harness didn't know something, it refused rather than guessed. An unknown
cost stops the budget (D48). No approver means deny (D57). No matching policy means deny (D58). Side
effects that can't be determined count as side effects (D126). The default toolbox is read-only (D37), and
the facade denies side effects unless you approve them (D176). Each default prevents a silent, expensive
mistake, at the cost of an occasional loud refusal, and loud refusals are cheap to fix.

**2. Same structure, different intent.** The most confusing patterns look identical in code: an object
holding another object with the same interface. What separates them is what the wrapper is *for*:

| Pattern | The wrapper... | Here |
|---|---|---|
| Decorator | adds behavior; every layer runs | `UsageTracker`, `Retry`, `DiskCache` |
| Proxy | controls access: whether, when, where | `BudgetGuard`, `LazyProvider`, `ToolboxView` |
| Chain of Responsibility | lets one handler take the request | `PolicyChain`, `FallbackChain` |
| Strategy | is chosen by the client, rarely changes | the provider an agent holds |
| State | replaces itself as things happen | the breaker's states, the lifecycle |
| Bridge | joins two hierarchies that both grow | agent types × providers |

**3. Order is behavior.** The wrapper stack (D46), the prompt sections (D23) and the policy chain (D56) all
mean something different in a different order. The fix each time was the same: put the order in exactly one
place (`build_stack()`, the Builder, the chain's list) and test it.

**4. Enforce roles in the API, not in the prompt.** Every time a prompt failed to hold a rule, the lasting
fix made the wrong thing impossible. `approve()` takes no text (D136). Hidden tools can't be called (D74).
Allowed recipients are checked in code (D138). A model will eventually do anything the interface allows.

**5. Patterns compose.** Real designs are combinations. Rewind is Memento plus Command. Autosave is Observer
driving Memento. Sub-agents are Composite plus Prototype plus Proxy plus Observer. The circuit breaker is a
Proxy by intent and State by implementation. Learning patterns one at a time is useful, but the skill is
seeing several in one piece of code.

**6. Python dissolves some patterns into the language.** A dict of classes is a factory. A generator is an
iterator. A module is a singleton. A function returning a pre-filled builder is a Director. Strategy and
Command can be plain functions. Knowing the pattern is what lets you recognize the idiom, and choose the
full class form only when it pays.

**7. Small interfaces make everything swappable.** `Provider` needs one method; `ToolSet` needs two. That's
why mocks, wrappers, proxies, views and team tools could stand in for the real thing everywhere, and why
321 tests run offline in about a second.

## The bugs the tests missed

Tests pass against the behavior you imagined. Real runs show the behavior you built. None of these was
caught by a test. Most were found by running the real thing; three (D103, D172, D182) turned up while
code was being reread or moved, which is the other habit worth keeping:

| Chapter | What happened | What changed |
|---|---|---|
| 6 | a tiny budget printed as `$0.0000` | six decimal places |
| 7 (D63) | the fallback hid an invalid API key by answering from another model | fall back only on transient errors |
| 7 (D65) | every turn retried a dead provider first | the circuit breaker in chapter 9 |
| 10 (D103) | a reused variable name would crash `--fallback --cache` | renamed |
| 13 (D136) | a reviewer approved its own rewrite | `approve()` takes no text |
| 13 (D142) | a reviewer couldn't check rules it had never seen | the mediator shares the brief |
| 14 (D146) | an answer listed four items when the file had two | a trace showed the *parent* invented them |
| 15 (D172) | the breaker's success bookkeeping never ran under an agent | act at `Completed`, drain to the end |
| 16 (D182) | a helper finishing deleted the main run's checkpoint | autosave ignores sub-agent events |

And the models themselves were a recurring lesson: they skip tools (chapter 1), miscount words (chapter 13),
invent facts (chapter 14), and keep their own unverified claims under review (chapter 17). A harness exists
largely to make those behaviors visible and bounded.

## The environment war stories

Not every hard problem was in the code.

**iCloud.** For most of the project, a strange bug kept returning: the editable-install file in `.venv` got
a macOS "hidden" flag, and Python 3.13 skips hidden `.pth` files, so `import miniharness` failed until the
flag was cleared. During stage 12, the test run simply *hung*. A traceback showed Python stuck reading a file
from disk. The cause: `~/Documents` was synced by iCloud Drive, which had **evicted** the contents of more
than 100,000 files in the repositories folder (virtual environments, `node_modules`, `.git` objects, even
source files), leaving placeholders that block on read while iCloud tries to download them. The fix was to
re-clone the repository into `~/Developer/repos` and rebuild the environment. Git repositories and virtual
environments don't belong in a synced folder.

**The heredoc.** A shell script that appended Markdown used an unquoted heredoc, so the shell executed every
backtick-quoted code name as a command, garbling the docs. The rule since then: quote heredocs (`<<'EOF'`).

**Pushing.** SSH pushes were blocked inside the sandbox, so every push went over HTTPS using the GitHub CLI's
credentials. Pushing by URL doesn't update the local `origin/main`, which made `git status` claim the branch
was "ahead" when it wasn't. A fetch into the remote-tracking ref fixed the display.

**The Anthropic key.** It stopped working partway through, so the Anthropic paths for checkpoint replay
(D106), streaming (D170) and pricing are tested only against fake clients. They're marked unverified in the
decision log, and they're the first things to re-check once the key is replaced.

## The questions left open

Twenty-five decisions are still open. They're not failures: each one is a design question the project chose
not to answer yet, with its options and trade-offs already written down. Grouped by theme:

**Concurrency and execution guarantees.** Tools run one at a time, and a surprising amount of the design
depends on that (D39): trace building, event order, checkpoint semantics. Resuming re-runs pending tool
calls, so execution is at-least-once, not exactly-once (D117). History has no run boundaries and lives only
in memory (D40).

**Streaming edge cases.** Retry and fallback can't switch after the first token (D159). An abandoned stream
has unknown cost (D160), and with the facade's default budget that blocks the next call (D179). Only text
streams, not tool arguments or reasoning (D169). A subclass that overrides only `think()` is bypassed when
streaming is on (D166).

**Multi-agent semantics.** A sub-agent's budget stop doesn't stop its parent (D131), and a delegation can't
be undone as one unit (D127). Team turns cost an extra model call (D139). Mechanical rules should be
validators, not reviewer judgment (D143). Self-review shares the model's blind spots (D197). Helpers are
read-only only (D184).

**Human in the loop.** Approval is synchronous (D91), but saved checkpoints now make asynchronous approval
possible (D118): pause, save, exit, and resume when someone answers.

**Abstractions that leak.** Anthropic's raw content (D8), mixed-provider conversations after a fallback
(D67), code that has to see through proxies (D73), and events that carry live mutable objects (D100).

**The rest.** No Abstract Factory (D14), a plain-string prompt that can't carry a cache breakpoint (D25), a
hardcoded price table (D52), `max_steps` raising instead of stopping (D90), and no event for unexpected
errors (D101).

## Where to go next

Three directions would each teach something new:

1. **Concurrent tools (D39).** Run read-only tool calls in parallel with `asyncio`, and watch which earlier
   decisions break: trace pairing, event order, checkpoints. It's the best possible test of how much a
   design depends on an assumption nobody wrote down.
2. **Asynchronous approval (D91, D118).** Add an `AwaitingApproval` state and an approver that can say
   "later". It combines State, Memento and Chain of Responsibility into a feature real harnesses need.
3. **Validators for teams (D143).** Let `approve()` run code checks first, so the mediator rejects a
   six-word slogan before the model ever gets to judge it.

Whichever you pick, start the way this project did: write the decision entry first, with the options and
their trade-offs, and build it second. That habit was the real subject of this book.
