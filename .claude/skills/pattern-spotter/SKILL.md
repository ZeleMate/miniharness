---
name: pattern-spotter
description: Reviews a codebase at a given path through the lens of the miniharness book. Reports which design patterns are already there, where a pattern would fix a visible smell, which of the book's anti-patterns appear (catch-all fallbacks, singleton globals, rules enforced only in prompts, wrapper order not pinned by a test, fail-open defaults), and where no pattern is the right call. Every finding cites file:line plus the book chapter and DECISIONS.md entry. Use when someone wants to apply the miniharness patterns to their own or another project ("spot patterns in ./src", "which design patterns does ~/code/my-agent use", "find the anti-patterns from the book in this repo", "where would Strategy or Observer help in my code"). Not for learning a chapter (use tutor) or re-implementing a stage (use rebuild).
---

# Spot patterns in a codebase

Apply what the book teaches to code the learner cares about. The book's tables say what each pattern
looks like and what goes wrong; this skill turns them into an evidence-backed review of a real
codebase. The point is transfer: the learner sees the same ideas in code they didn't write for the book.

This is a read-only review. Don't edit, format, install into or run code that changes the target. Running
its tests is fine only if the learner asks.

## Inputs

- **Target path** (required). If none is given, ask. `./src` means the current repository's `src/`;
  pointing it at `miniharness` itself is a valid exercise, since its patterns are known.
- **Optional focus**: one pattern, anti-patterns only, or one directory.

## The reference material

Read `references/catalog.md` first. It condenses, with chapter and D-entry numbers:

- the appendix's **Which pattern when** table (`docs/book/appendix.md`),
- the epilogue's **Same structure, different intent** table and **Failure modes tests don't catch**
  (`docs/book/20-epilogue.md`),
- the five anti-patterns to check, with search hints,
- when *no* pattern is the right call (chapter 3, D14).

When a finding cites a D-entry, open it in `DECISIONS.md` and make sure it says what you claim. A wrong
citation teaches the wrong lesson.

## Workflow

### 1. Survey

Get the shape before searching: languages, size (`git ls-files | wc -l` or `find`), entry points, the
main modules, where tests live. For a large codebase, say which part you reviewed and why (the core
domain logic and its integration points usually carry the most patterns and smells). Skip vendored,
generated and test-fixture code unless asked.

The catalog's search hints are Python-flavoured. For other languages, translate the idea (an interface
with one implementation, a wrapper type that implements what it wraps), not the regex.

### 2. Search, then read

Use the search hints to find candidates, then **read every candidate in context** before it becomes a
finding. A grep hit is a lead, not evidence. In particular:

- Wrapper-shaped classes are ambiguous; classify them by intent with the "Same structure, different
  intent" table. If name and intent disagree, that's worth reporting.
- For "decorator order not pinned by a test", look for the test too. The finding is the missing test or
  the order assembled in more than one place, not the stacking itself.
- For "rules enforced only in prompts", find the prompt text *and* confirm the code path that should
  reject a violation doesn't exist.
- For "fail-open default", trace what happens when the value is missing or unknown.

### 3. Decide what to report

Report a finding only when you can point at the line and explain the consequence. Prefer five solid
findings over twenty speculative ones. For each smell where a pattern would help, also consider the
"no pattern" option honestly: if the variation the pattern supports doesn't exist yet, the right
recommendation is to leave it and name the trigger that would change that (D14's approach).

## Report format

Use this structure. Omit a section only if it's empty, and say so in one line.

```markdown
# Pattern review: <path>

Scope: <what was reviewed, what was skipped, and why>.

## Patterns already present
- **<Pattern>**: `path/to/file.py:42` — <what plays which role>. Book: ch. N; D-entries.

## Smells a pattern would fix
- **<Smell> → <Pattern>**: `path:line` — <the evidence, and what the change would buy>.
  Cost: <what the pattern adds>. Book: ch. N; Dxx.

## Anti-patterns from the book
- **<Anti-pattern>**: `path:line` — <the evidence and the concrete failure it allows>.
  Fix in the book's terms: <one line>. Book: ch. N; Dxx.

## Where no pattern is the right call
- `path:line` — <why the current code is fine>. Revisit when <trigger>. Book: ch. 3; D14.

## Suggested next step
<One concrete thing to try, ideally linked to a PATTERNS.md "Try it" or a chapter to read.>
```

Each finding: the pattern or anti-pattern name in bold, a `file:line` the learner can open, one or two
sentences of evidence, and the book chapter plus at least one D-entry. Mark low-confidence findings as
"possible" rather than leaving them out silently.

Write in the book's neutral voice: describe what the code does and what it risks, without judging its
authors.
