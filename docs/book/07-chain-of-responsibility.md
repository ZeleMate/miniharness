# Chapter 7. Who decides?

*Pattern: [Chain of Responsibility](https://refactoring.guru/design-patterns/chain-of-responsibility). Code: `src/miniharness/tools/policy.py`, `FallbackChain` in
`providers/wrappers.py`.*

## A chain is not a stack

Chapter 6's decorator stack and this chapter's chains look alike, since both are sequences of objects
with the same interface. The difference is the heart of the pattern:

- In a **Decorator** stack, *every* layer runs, each adding something on the way through.
- In a **Chain of Responsibility**, each handler gets a chance to *handle* the request and stop it there.
  The request only travels further if a handler passes it on.

A decorator answers "what else happens?". A chain answers "**who deals with this?**" (D55). This stage
built two chains: one deciding whether a tool call may run, and one deciding which model answers.

## The permission chain

Whether a tool may run depends on several independent rules: a deny list, a call quota, letting read-only
tools through, asking a human about anything with side effects. Written as one `if` ladder inside the
Toolbox, they'd be tangled together. As a chain, each rule is its own small object:

```python
policy = PolicyChain([
    DenyTools({"send_email"}),
    MaxCalls("write_file", 5),
    AllowReadOnly(),
    AskBeforeSideEffects(),
], approver=terminal_approver)
```

Each policy returns a decision or `None` (no opinion), and **the first decision wins**. You chose a plain
list over GoF's linked handlers, where each handler holds a `next` reference (D56). Same intent, different
structure: the list can't suffer the classic linked-chain bug of a handler forgetting to call `next`, and
reordering means editing a list.

When nothing decides, the call is **denied** (D58), the same fail-closed stance as the budget.

## Separating "ask" from "how to ask"

A refinement came up while designing: a policy can return a third verdict, `ASK`, and the chain resolves
it with an injected approver (D57). That splits two concerns. *Deciding to ask* is policy. *How to ask*
(a terminal prompt, a Slack message, a web UI) is infrastructure. The policies stay pure and testable, and
an unattended run with no approver turns `ASK` into `DENY`.

Every decision also records its reason and *which policy made it* (D61), because "why was this allowed?"
is the first question anyone asks when a permission system surprises them:

```
denied write_file: write_file needs approval and was declined (by AskBeforeSideEffects)
```

A denial goes back to the model as the tool's result (D59), and in the live run the model explained to the
user that it lacked permission and asked how to proceed. The run degraded gracefully instead of crashing.

One honest renaming: the preview called a policy `RateLimit`, but it had no time window, only a total. It
became `MaxCalls` (D62). Names that promise behavior the code doesn't have are small lies that cost
debugging time later.

## The fallback chain, and the bug it hid

The second chain tries providers in order: `FallbackChain([anthropic, openrouter])`. If the first fails,
the next gets the request.

The first version fell back on *any* API error. Then a live run, with an Anthropic model as primary, got
`401 invalid x-api-key`, and the chain quietly answered with DeepSeek instead. It looked like success. In
fact a broken key was being **hidden**, and money was being spent on a different model.

The fix (D63) is a lesson that reaches well beyond this project: decide which failures mean "try someone
else" and which mean "you have a bug". Connection errors, timeouts, rate limits and server errors are
*transient*, so falling back makes sense. A bad key, a malformed request or an unknown model is
*configuration*, and falling back only hides it. The chain now falls back on transient errors only, and
configuration errors surface loudly. **A fallback that catches everything is a bug-hider.**

A refusal is treated as a reason to try the next provider too, but if the last one refuses, its refusal is
returned as a normal answer (D64): a refusal is an answer, not an error.

## Problems noticed and deferred

The same live run exposed another flaw: "fell back" was printed *twice*, because each of the agent's model
calls tried the broken provider first again (D65). That costs latency and money on every turn. The fix is a
circuit breaker, and it waited for chapter 9, where it's a textbook example of State. Two subtler gaps were
logged too: a refused response that the chain skips was still billed, but an outer tracker never sees it
(D66, fixed in the review before publishing, D213), and after a fallback one conversation mixes providers,
the `raw` leak from chapter 2 in action (D67).

## The one thing to remember

**A chain must be precise about what "not mine, pass it on" means.** The difference between a transient
failure and a configuration bug is the difference between resilience and hiding problems.

## Questions to think about

- Where would a `DenyPaths` policy (block writes outside `notes/`) go in the chain, and why?
- In a fallback chain you rely on, which errors cause a fallback? Could any of them be configuration bugs?
