---
name: rebuild
description: Guided re-implementation of one miniharness build stage by the learner. Checks out the code as it was just before that stage on a local learn/stage-N branch, states the problem from the book chapter without the solution, gives hints only on request, accepts the work with that stage's original tests, then compares the learner's design with the real stage diff and the DECISIONS.md entries. Use when someone in the miniharness repo wants to build, re-implement, rebuild, code or practice a stage or pattern themselves ("let me rebuild stage 7", "I want to implement the Decorator stage on my own", "practice the Observer stage from scratch", "start me on stage 11"). Not for reading or quizzing on a chapter (use tutor) or reviewing another codebase (use pattern-spotter).
---

# Rebuild a stage

The learner writes the code for one stage of `miniharness` themselves, starting from the commit just
before it. The repository's own history provides everything: the starting point (the stage commit's
parent), the acceptance tests (the stage commit's tests) and a reference design (the stage commit's
`src/` diff, explained by `DECISIONS.md`). No repo preparation is needed.

The value is in the learner doing the design work. Every step below protects that: state the problem but
not the answer, hint only when asked, and show the reference only after the tests pass or the learner
gives up.

## Ground rules

- **Never push, and never modify `main`.** All work happens on a local `learn/stage-N` branch in a
  separate worktree. Don't commit, reset or check out anything in the main checkout. Committing on the
  learn branch is fine if the learner wants checkpoints; it stays local.
- **Don't write the learner's solution.** Read, run and explain their code; point at failing behavior.
  Write code only when they explicitly ask for it, and then the smallest piece they asked for.
- **Read the reference material from the main checkout.** The parent commit predates the book, most of
  `DECISIONS.md` and these skills, so those files don't exist (or are incomplete) inside the learn
  worktree. Read `docs/book/`, `DECISIONS.md` and `PATTERNS.md` from the main checkout (or with
  `git show main:<path>`).

## Step 1: Resolve the stage

Read `references/stages.md` for the stage → commit map, the acceptance test files and the D-entry
range. Accept a number (1–19), a pattern name or an alias from that file. If the request is ambiguous,
ask which stage.

Stage 1 is the root commit and has nothing before it. Say so and offer the Template Method **Try it**
exercise from `PATTERNS.md` instead.

## Step 2: Set up the worktree

Check before creating anything:

1. `git status --porcelain` in the main checkout. Uncommitted changes are fine (a worktree doesn't touch
   them), but mention them.
2. `git cat-file -e <commit>^{commit}` for both the stage commit and its parent. If either is missing, the
   clone is probably shallow: suggest `git fetch --unshallow` and stop until the learner has run it.
3. Whether `learn/stage-N` already exists (`git branch --list learn/stage-N`). If it does, ask whether to
   resume it or start over. Starting over deletes their earlier attempt, so confirm explicitly before
   `git worktree remove` / `git branch -D`.

Then create the worktree next to the repository, not inside it (so the main checkout's ruff and pytest
don't pick it up):

```bash
git worktree add ../miniharness-stage-N -b learn/stage-N <parent>
cd ../miniharness-stage-N
uv sync
uv run pytest -q
```

Tell the learner why `uv sync` is needed: early stages predate ruff and mypy, and the lockfile differs
from `main`'s. The baseline `pytest` run should be green; it proves the starting point works before they
change anything. If the learner prefers working in place, `git switch -c learn/stage-N <parent>` also
works, but then the book and these skills disappear from the working tree until they switch back.

## Step 3: State the problem, not the solution

Read the stage's chapter in `docs/book/`. Chapters open with the problem (the smell the previous stage
left, the requirement that forces a change) and then present the design. Use only the problem part:

- what hurts in the current code, with `file:line` references into the **learn worktree** so the learner
  sees the smell in the code they're about to change;
- the capability the stage has to add, at the level of a feature request ("decide per tool call whether
  it may run", "every tool call can be undone");
- constraints the chapter states up front (offline tests, no new dependencies, existing tests keep
  passing).

Don't name the pattern's structure, the class layout, or which options the chapter weighs. If the
chapter title or the learner already names the pattern, that's fine; the *how* is still theirs.

The stage's D-entries are the answers. Wherever an entry records a choice between options (what happens
when no rule decides, which errors trigger a fallback, snapshot vs inverse undo), turn it into an **open
question** for the learner ("Decide what happens when no rule applies, and why"), not a requirement.
Skim the D-entry titles in the stage's range before writing, and check the draft against them: a
sentence that restates a D-entry's "Chosen" line gives the design away.

Then give the **interface contract**. The acceptance tests import specific names and call specific
signatures, and a learner can't guess those. Read the stage commit's test files
(`git show <commit>:tests/<file>`) and give only:

- the import lines (module paths and public names),
- constructor and function signatures the tests call, including attributes they read.

Keep it compact: a short list, not a reference manual. Present it as "the tests will import and call…",
not as test code. Don't list the behaviors the tests assert; many of them encode the stage's decisions,
and the acceptance run reveals them anyway. Offer them, and the full test files, as an option for
learners who prefer to work test-first.

End with: "Ask for a hint whenever you want one, or tell me when you're ready to run the acceptance
tests."

## Step 4: Hints on request

Give hints only when the learner asks, one level at a time, and say which level it is so they can ask
for the next:

1. **Restate the force.** Which requirement their current approach doesn't satisfy, or which test
   behavior it will fail.
2. **Name the idea.** The pattern, or the property that matters ("the wrappers have to look like the
   thing they wrap"), with a pointer to the relevant `PATTERNS.md` entry or appendix row.
3. **Sketch the shape.** Class and method names and who holds a reference to whom, in a few lines of
   prose or a signature-only outline. Still no method bodies.

When they share code, read it and run it. Comment on what it does, not on how far it is from the
reference.

## Step 5: Acceptance

When the learner says they're ready, bring in the stage's tests inside the learn worktree:

```bash
git diff --name-status <parent> <commit> -- tests/
git show <commit>:tests/test_wrappers.py > tests/test_wrappers.py   # one line per listed file
uv run pytest -q
```

Report results plainly: how many passed, and for each failure whether it's an **interface mismatch**
(an import or a signature the learner named differently) or a **behavior gap**. Interface mismatches are
cheap to fix and say nothing about the design; behavior gaps are the interesting ones, so explain what the
test expects in terms of the requirement it encodes. Let the learner fix things and rerun. If the learner
deliberately chose a different interface, that's legitimate: note the difference and move on to the
comparison.

## Step 6: Compare with the reference

After the tests pass, or the learner asks to see the reference, compare the two designs:

```bash
git diff <parent> -- src/              # the learner's change, from the learn worktree
git diff <parent> <commit> -- src/     # the stage commit
```

Structure the comparison as:

- **Same decisions.** Where the learner arrived at the reference design, name the D-entry that records
  it, so they can read the trade-off.
- **Different decisions.** For each real difference, check the stage's section of `DECISIONS.md` (range
  in `references/stages.md`). Often the learner's choice is one of the options a D-entry lists and
  rejects; quote the reasoning and its cost. Sometimes the learner's choice is simply also valid, or
  better for a different context. Say so; the reference isn't the only correct answer.
- **What the reference has that the learner's doesn't.** Usually edge cases a D-entry exists for (fail
  closed, ordering, error types). Point at the test that covers it, if one does.

Cite D-entries by number (**D46**) with their one-line title, and `file:line` in both trees.

Finish by pointing at the chapter's **one thing to remember** and, if the learner wants to record what
they learned, the pattern's empty **Your notes** slot in `PATTERNS.md` (the `tutor` skill can write it
in their words).

## Cleanup

Leave the worktree in place unless the learner asks to remove it. If they ask, use a guarded flow:

1. Ask for explicit confirmation (for example: **"Type: DELETE STAGE N"**). Do not run deletion commands
   until the learner provides that exact confirmation.
2. Verify targets exist (`git worktree list`, `git branch --list 'learn/stage-N'`).
3. Remove the worktree, then delete the branch with the non-forcing form first:

```bash
git worktree remove ../miniharness-stage-N
git branch -d learn/stage-N
```

4. If `git branch -d` fails because the branch is not fully merged, explain why and ask whether to force
   delete. Only run `git branch -D learn/stage-N` after an explicit yes.
