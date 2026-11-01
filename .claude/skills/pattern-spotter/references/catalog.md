# Catalog: what to look for, and where the book explains it

Condensed from `docs/book/appendix.md` ("Which pattern when") and `docs/book/20-epilogue.md` ("Same
structure, different intent", "Failure modes tests don't catch"). Those files are the source of truth;
reread them if a row here seems to disagree. Search hints are starting points for `grep`, not verdicts:
every hit has to be read in context before it becomes a finding.

## Contents

1. Patterns: signals and references
2. Same structure, different intent
3. Anti-patterns
4. Where no pattern is the right call

## 1. Patterns: signals and references

| Pattern | Chapter | Key D-entries | Already present when you see... | Would help when you see... |
|---|---|---|---|---|
| Template Method | 1 | (stage 1 has none) | a base class with a fixed loop calling overridable hooks | the same loop copy-pasted with small differences |
| Strategy | 2 | D2, D4 | an object holding an interchangeable collaborator behind one interface | `if kind == "a": ... elif kind == "b": ...` choosing an algorithm |
| Adapter | 2 | D3, D8 | functions or classes converting between a vendor format and your own types | vendor types leaking through the codebase; conversion inlined at call sites |
| Factory | 3 | D12, D13, D14 | a name → class registry, `create_x("spec")` | the same `if/elif` that builds objects from a string, repeated in several callers |
| Builder (+ Director) | 4 | D21, D23, D26 | step-by-step construction with ordering rules, `build()` | string concatenation with order-sensitive sections; a constructor with rules between arguments |
| Command | 5 | D29, D30, D33 | actions as objects with `execute`/`undo`, a history list | actions you need to log, queue, replay or undo, done as bare function calls |
| Decorator | 6 | D42, D46, D48 | a class that takes X, is an X, adds one behavior, delegates the rest | the same cross-cutting code (retry, caching, metrics) copied into every implementation |
| Chain of Responsibility | 7 | D56, D58, D63 | a list of handlers where the first verdict wins | a long `if` ladder of permission or routing rules |
| Proxy | 8 | D68, D72, D74 | a stand-in controlling access: lazy creation, permission, quota | expensive construction at import time; access checks scattered across callers |
| State | 9 | D79, D80, D83 | one class per state, the context delegating to its current state | `if self.mode == ...` in many methods; booleans that must change together |
| Observer | 10 | D93, D95, D97 | an event bus or listeners with subscribe/notify | logging, metrics and UI calls hard-coded into core logic |
| Memento | 11 | D105, D108, D109 | snapshots that can be restored | ad-hoc save/restore that misses part of the state |
| Prototype | 11 | D107, D115 | `copy()`/`fork()` that keeps the configured type | re-running a long constructor to get a near-identical object |
| Composite | 12 | D119, D121, D126 | a group that implements the same interface as one item | code that special-cases "one" vs "many" everywhere |
| Mediator | 13 | D133, D136, D138 | peers that talk only through a coordinator | peers holding references to each other in a tangle |
| Visitor | 14 | D145, D151, D152 | `accept`/`visit` over a stable set of node types | many `isinstance` switches over the same node types, one per operation |
| Iterator | 15 | D156, D165, D172 | generators, `__iter__`, caller-paced processing | callbacks for results that arrive over time where the caller wants to pull or stop early |
| Facade | 16 | D173, D175, D176 | one entry point hiding a subsystem's wiring | every caller repeating the same ten lines of setup |
| Bridge | 17 | D188, D190, D198 | two hierarchies joined by composition | a class explosion like `PlannerOpenAI`, `PlannerAnthropic`, `ReviewerOpenAI`... |
| Dependency injection (instead of Singleton) | 18 | D202, D203, D204 | collaborators passed in; one default instance at the edge | see "singleton globals" below |

## 2. Same structure, different intent

Wrapper-shaped code (an object holding another with the same interface) is ambiguous. Classify it by
what the wrapper is *for* (epilogue, idea 2):

| Pattern | The wrapper... | miniharness example |
|---|---|---|
| Decorator | adds behavior; every layer runs | `UsageTracker`, `Retry`, `DiskCache` |
| Proxy | controls access: whether, when, where | `BudgetGuard`, `LazyProvider`, `ToolboxView` |
| Chain of Responsibility | lets one handler take the request | `PolicyChain`, `FallbackChain` |
| Strategy | is chosen by the client, rarely changes | the provider an agent holds |
| State | replaces itself as things happen | the breaker's states, the lifecycle |
| Bridge | joins two hierarchies that both grow | agent types × providers |

When a class's name and its intent disagree (a "Decorator" that only decides whether the call happens),
report it: the book makes the same reclassification for `BudgetGuard` (chapter 8, D72).

## 3. Anti-patterns

| Anti-pattern | Search hints | What to confirm by reading | Chapter, D-entries |
|---|---|---|---|
| **Catch-all fallback**: a fallback or retry that triggers on every error, so a bad key or unknown model is silently answered by something else | `except Exception`, `except:`, `except BaseException`, fallback / retry loops, `or default_client` | the handler swallows configuration errors (auth, not-found, validation), not only transient ones (timeouts, rate limits, 5xx) | ch. 7, D63; epilogue failure-mode table (7, D63) |
| **Singleton globals**: a module-level mutable registry, cache or client that tests must reset or monkeypatch | module-level `dict`/`list` that is mutated, `global `, `_instance`, `getInstance`, `@lru_cache` on a zero-argument getter, `@functools.cache` returning a client | it holds mutable state shared across callers, and tests patch or clear it. A constant or a ContextVar for per-execution facts is not this smell (D210) | ch. 3 (D17), ch. 18 (D202, D203) |
| **Rules enforced only in prompts**: an invariant stated to a model ("never", "only", "must not", "do not call") with no code check behind it | prompt strings and templates containing `never`, `only`, `must not`, `do not`; tool schemas without server-side validation | the rule matters (permissions, recipients, approval, formats) and nothing in code rejects a violation | ch. 13 (D136, D138, D143); epilogue idea 4 |
| **Decorator order not pinned by a test**: wrappers whose order changes behavior, composed in more than one place or with no test of the order | nested wrapper construction `A(B(C(x)))`, middleware lists, `@` stacks on functions with caching/retry/auth | the order is assembled in several places, or no test asserts the behavior that depends on it (a cache hit counted as cost, retries escaping a budget) | ch. 6 (D46); epilogue idea 3 (also D23, D56) |
| **Fail-open default**: when something is unknown or missing, the code allows | `.get(key, True)`, `return True` at the end of a permission check, `default=allow`, `cost or 0`, `except: pass` in a guard, empty allow-lists meaning "everything" | the default is reached when information is missing, and it permits the action | ch. 6 (D48), ch. 7 (D58), ch. 5 (D37), ch. 12 (D126), ch. 16 (D176); epilogue idea 1 |

Other failure modes from the epilogue's table are worth a finding when they show up clearly: display
precision too low for the smallest real value (ch. 6), bookkeeping after a generator's last `yield`
(ch. 15, D172), a reused loop variable shadowing one read later (ch. 10, D103).

## 4. Where no pattern is the right call

The book's rule is "no speculative patterns" (preface, rule 3; ch. 3; D14): a pattern needs a concrete,
present reason. Flag these as *leave it alone*:

- a single implementation behind an interface built "for later" (an Abstract Factory with one family, a
  Strategy with one strategy) — D14 records the trigger to wait for instead;
- a two-branch `if` that has not grown in the history (`git log -L` or blame shows it unchanged);
- class-shaped code where a Python idiom does the job: a dict of classes as a factory, a generator as an
  iterator, a function as a Strategy or Command, a module as the one instance (epilogue idea 6);
- a pattern added where its cost (indirection, more classes, harder reading) exceeds the variation it
  supports.

Phrase these as "no pattern needed", with the trigger that would change the answer (D14's style: "build
it when a second X appears").
