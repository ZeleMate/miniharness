# Preface: how this book works

Catalogues of design patterns, like [refactoring.guru](https://refactoring.guru/design-patterns), explain
*what* each pattern is. They can't show you what it's like to *need* one. This book takes the other route:
it builds a real system, a small harness for LLM agents, and introduces each pattern only at the point
where the code stops working well without it.

An agent harness suits this, because almost every classic pattern has a natural home in it. Swapping model
providers is Strategy. Translating between their message formats is Adapter. Tool calls you can undo are
Command. Permission rules are Chain of Responsibility. Sub-agents are Composite. If you work on agentic
systems, the patterns stop being textbook diagrams and become answers to problems you already know.

## The method

Four rules shape every chapter. They matter more than any single pattern.

**1. Naive first, then refactor.** The first version of the provider code is deliberately bad: one
`call_llm()` function with an `if provider == "openrouter": ... elif provider == "anthropic": ...` ladder,
SDK clients rebuilt on every call, translation code buried inline. You can't appreciate a pattern until
you've seen the problem it solves, so the problem comes first and the fix second.

**2. Lock down behavior before changing structure.** Before the first refactor come *characterization
tests*: tests that pin down exactly what the existing code sends to each API, warts and all, using fake
SDK clients so they run offline. The refactor can then change everything about the structure while those
assertions guarantee that the payloads don't change by a single byte (D1).

**3. No speculative patterns.** A pattern needs a concrete reason: a second provider, a test that's hard to
write, a failure a real run can produce. Without one, the pattern waits. Abstract Factory waits forever
(D14). Knowing when *not* to apply a pattern is as useful as knowing how to apply it.

**4. Run it for real.** Tests confirm the behavior you designed; running against a real model shows the
behavior you actually built. Models use tools in ways tests don't anticipate, and several design rules in
this book exist because of failure modes that only appear with a real model in the loop. The epilogue
collects them.

## Chapters and the design rationale

Each chapter is one stage of the build: the problem that makes a pattern necessary, the options, the
design the code uses and why, and the trade-offs. Chapters end with **the one thing to remember** and a few
**questions to think about**.

Decisions are cited by number (**D63**). Each has a full entry in
[`DECISIONS.md`](../../DECISIONS.md) with every option considered and what the chosen one costs. The book
is the readable path through that file.

## The stack

Python 3.13 (3.12 and up supported), managed with `uv`. The OpenAI SDK pointed at OpenRouter, so cheap
models can be used for live testing, plus the Anthropic SDK, included specifically because its message
format differs from OpenAI's in ways that require an Adapter. pytest throughout; the whole suite runs
offline in about a second, using a mock provider and fake SDK clients.

## Mistakes are part of the material

The book keeps the failure modes in, because they teach what the successful designs don't: a fallback
that hides a broken API key, a reviewer agent that approves its own rewrite, a generator whose cleanup
never runs. Each one is stated as a general rule you can apply to your own code.
