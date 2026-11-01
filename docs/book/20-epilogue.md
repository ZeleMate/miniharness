# Epilogue: what it all adds up to

Nineteen stages and about two hundred and thirty recorded decisions. The individual patterns matter less
than the ideas that keep coming back across them. This chapter collects those ideas, the failure modes that
teach the most, and the questions the design deliberately leaves open.

## Seven ideas that keep coming back

**1. Fail closed.** Whenever the harness doesn't know something, it refuses rather than guesses. An unknown
cost stops the budget (D48). No approver means deny (D57). No matching policy means deny (D58). Side effects
that can't be determined count as side effects (D126). The default toolbox is read-only (D37), and the
facade denies side effects unless you approve them (D176). Each default prevents a silent, expensive
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
mean something different in a different order. The fix each time is the same: put the order in exactly one
place (`build_stack()`, the Builder, the chain's list) and test it.

**4. Enforce roles in the API, not in the prompt.** Wherever a prompt can't hold a rule, the lasting fix
makes the wrong thing impossible. `approve()` takes no text (D136). Hidden tools can't be called (D74).
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
why mocks, wrappers, proxies, views and team tools can stand in for the real thing everywhere, and why the
whole test suite runs offline in about a second.

## Failure modes tests don't catch

Tests pass against the behavior you imagined. Real runs show the behavior you built. Each of these is a
failure mode that a unit test written from the design wouldn't catch; some appear only with a real model in
the loop, others only when code is reread or moved:

| Chapter | Failure mode | Design rule |
|---|---|---|
| 6 | a tiny budget prints as `$0.0000` | display enough precision for the smallest real value |
| 7 (D63) | a fallback hides an invalid API key by answering from another model | fall back only on transient errors |
| 7 (D65) | every turn retries a dead provider first | a circuit breaker (chapter 9) |
| 10 (D103) | a reused loop variable shadows one read later | name loop variables for what they iterate |
| 13 (D136) | a reviewer approves its own rewrite | `approve()` takes no text |
| 13 (D142) | a reviewer can't check rules it has never seen | the mediator shares the brief |
| 14 (D146) | an answer lists four items when the file has two | a trace tree shows which layer invented them |
| 15 (D172) | bookkeeping after a generator's last `yield` never runs | act at `Completed`; consumers drain to the end |
| 16 (D182) | a helper finishing deletes the main run's checkpoint | autosave ignores sub-agent events |

Models themselves are a recurring source: they skip tools (chapter 1), miscount words (chapter 13), invent
facts (chapter 14), and keep their own unverified claims under review (chapter 17). A harness exists
largely to make those behaviors visible and bounded.

## Practical lessons outside the code

- **Keep repositories and virtual environments out of cloud-synced folders.** Sync clients can evict file
  contents and leave placeholders that block on read, which shows up as hung test runs and failed imports.
- **Quote heredocs that contain Markdown** (`<<'EOF'`). An unquoted heredoc makes the shell execute every
  backtick-quoted name as a command.
- **Mark what hasn't been verified.** The Anthropic paths for checkpoint replay (D106), streaming (D170) and
  pricing are tested against fake clients only, and the design rationale says so. An explicit "unverified"
  is more useful than an implied "works".

## The questions left open

About two dozen decisions are open. They're not failures: each is a design question deliberately left
unanswered, with its options and trade-offs already written down. Grouped by theme:

**Concurrency and execution guarantees.** Read-only tool calls can run together, but sub-agents still run one
at a time, and a surprising amount of the design depends on that (D216): trace building, the shared provider
stack, budget checks. Resuming re-runs pending tool calls, so execution is at-least-once, not exactly-once
(D117). History has no run boundaries and lives only in memory (D40).

**Streaming edge cases.** Retry and fallback can't switch after the first token (D159). An abandoned stream
has unknown cost (D160), and with the facade's default budget that blocks the next call (D179). Only text
streams, not tool arguments or reasoning (D169). A subclass that overrides only `think()` is bypassed when
streaming is on (D166).

**Multi-agent semantics.** A sub-agent's budget stop doesn't stop its parent (D131), and a delegation can't be
undone as one unit (D127). Team turns cost an extra model call (D139). Mechanical rules should be validators,
not reviewer judgment (D143). Self-review shares the model's blind spots (D197). Helpers are read-only only
(D184).

**Human in the loop.** Approval is synchronous (D91), but saved checkpoints make asynchronous approval
possible (D118): pause, save, exit, and resume when someone answers.

**Abstractions that leak.** Anthropic's raw content (D8), mixed-provider conversations after a fallback (D67),
code that has to see through proxies (D73), and events that carry live mutable objects (D100).

**The rest.** No Abstract Factory (D14), a plain-string prompt that can't carry a cache breakpoint (D25), a
hardcoded price table (D52), `max_steps` raising instead of stopping (D90), and no event for unexpected
errors (D101).

## Where to go next

Three directions each teach something new:

1. **Parallel sub-agents (D216).** Read-only *leaf* tools already run together (chapter 19, including the
   ContextVar trap of D220). Letting sub-agents overlap is where the earlier decisions really break: trace
   pairing (D148), budget checks, the lazy proxy and the breaker. It's the best test of how much a design
   depends on an assumption.
2. **Asynchronous approval (D91, D118).** Add an `AwaitingApproval` state and an approver that can say
   "later". It combines State, Memento and Chain of Responsibility into a feature real harnesses need.
3. **Validators for teams (D143).** Let `approve()` run code checks first, so the mediator rejects a six-word
   slogan before the model ever gets to judge it.

Whichever you pick, follow the book's method: write the decision entry first, with the options and their
trade-offs, and build it second.
