# Preface: how this project worked

The idea was simple. Reading about design patterns on [refactoring.guru](https://refactoring.guru/design-patterns) explains *what* they are, but not
what it feels like to *need* one. So instead of studying patterns in the abstract, we built something real,
a small harness for LLM agents, and let each pattern arrive only when the code started to hurt without it.

An agent harness is a good teacher for this, because almost every classic pattern has a natural home in
it. Swapping model providers is Strategy. Translating between their message formats is Adapter. Tool calls
you can undo are Command. Permission rules are Chain of Responsibility. Sub-agents are Composite. If you
work on agentic systems, the patterns stop being textbook diagrams and become answers to problems you've
already had at work.

## The rules we followed

Four habits shaped every stage. They're worth more than any single pattern.

**1. Naive first, then refactor.** The first version of the provider code was deliberately bad: one
`call_llm()` function with an `if provider == "openrouter": ... elif provider == "anthropic": ...` ladder,
SDK clients rebuilt on every call, translation code buried inline. That wasn't laziness. You can't
appreciate a pattern until you've felt the problem it solves, so the smell came first, and the fix second.

**2. Lock down behavior before changing structure.** Before the first refactor, we wrote
*characterization tests*: tests that pin down exactly what the existing code sends to each API, warts and
all, using fake SDK clients so they run offline. Then the refactor could change everything about the
structure, while those assertions guaranteed the payloads didn't change by a single byte (D1).

**3. No speculative patterns.** A pattern needs a concrete reason: a second provider, a test that's hard to
write, a bug a real run exposed. When there was no reason, the pattern waited. Abstract Factory waited
forever (D14). Learning when *not* to apply a pattern turned out to be one of the most useful lessons.

**4. Run it for real.** Every stage ended with a live run against a real model through OpenRouter. The
tests confirmed the behavior we imagined; the live runs revealed the behavior we had actually built. A
surprising number of the best design decisions in this book came from a model doing something nobody
expected. The epilogue lists them.

## Pair mode, and the decision log

The project ran in "pair mode": before writing code, the big design questions were asked out loud, with
two to four concrete options, a code preview of each, and a recommendation. You made those calls. The
smaller decisions made while implementing were listed afterwards, with their alternatives, so you could
overturn any of them.

All of it went into `DECISIONS.md`: 213 numbered entries by the end. Each says what the options were, why
one won, what it cost, whether it's settled or still open, and when to revisit it. Decisions you made are
marked "(your call)". The ones found in live runs say so.

This book is the readable version of that log. Where a chapter mentions **D63**, the full entry is there if
you want every detail.

## The stack

Python 3.13, managed entirely by `uv`. The OpenAI SDK pointed at OpenRouter, so cheap models like DeepSeek
could do most of the live testing, plus the Anthropic SDK, included specifically to create the need for
an Adapter, because its message format differs from OpenAI's in interesting ways. pytest throughout: 321
tests by the end, all running offline in about a second.

## A note on what went wrong

This book doesn't hide the mistakes, because they're instructive. A fallback that hid a broken API key. A
reviewer agent that approved its own rewrite. A shell script that executed the text of a Markdown file.
And a whole afternoon lost to iCloud quietly evicting files from the repository. Each one taught something
the successful parts didn't.
