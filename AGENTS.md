# Agent guide

`miniharness` teaches the classic design patterns through a small LLM agent harness. The material:
`docs/book/` (one chapter per build stage), `DECISIONS.md` (design rationale, cited as **D1**–**D228**),
`PATTERNS.md` (a workbook with a **Try it** exercise and an empty **Your notes** slot per pattern), and the
code in `src/miniharness/`.

## Learning workflows

Three workflows are written as skills under `.claude/skills/`. Claude Code loads them automatically; any
other agent can follow the same steps by reading the `SKILL.md` file (and its `references/`) when a
request matches.

| Workflow | Use when the learner wants to... | Instructions |
|---|---|---|
| **tutor** | study one chapter or pattern: Socratic walkthrough of the real code, a quiz on the chapter, a check of their Try it answer, and notes in `PATTERNS.md` in their words | [`.claude/skills/tutor/SKILL.md`](.claude/skills/tutor/SKILL.md) |
| **rebuild** | re-implement a stage themselves, starting from the commit before it on a local `learn/stage-N` branch, accepted by that stage's original tests and compared with the real diff | [`.claude/skills/rebuild/SKILL.md`](.claude/skills/rebuild/SKILL.md) |
| **pattern-spotter** | review their own codebase for patterns, smells, the book's anti-patterns, and places where no pattern is needed, with `file:line`, chapter and D-entry for each finding | [`.claude/skills/pattern-spotter/SKILL.md`](.claude/skills/pattern-spotter/SKILL.md) |

## Rules for any agent working here

- Use `uv` for everything Python: `uv sync`, `uv run pytest`, `uv run ruff check .`. Never pip or venv.
- Tests run offline with the mock provider. Don't call a paid model API without asking.
- `rebuild` never pushes and never modifies `main`; learner work stays on local `learn/*` branches.
- Docs are written in a neutral, objective voice: patterns, trade-offs and evidence, not personal stories.
- CI requires GitHub `noreply` commit emails and rejects absolute home-directory paths in tracked files.
