---
name: spec-review
description: Check the current branch's diff against the issue, PR description or DECISIONS.md entry it is meant to implement, and report unmet requirements and scope creep. Use before opening a PR, or when asked whether a change "does what was asked".
---

# Spec review

Goal: say whether this diff implements what was asked, and nothing else. Correctness and style are covered by `/code-review`, the `code-reviewer` subagent and CI; stay on requirements.

1. **Find the spec.** In order: the PR body (`gh pr view --json body,title`), an issue number in the branch name or commits (`gh issue view <n>`), the `DECISIONS.md` entries the change adds or cites, or ask the user. If none exists, stop and say so.
2. **List the requirements** as short, checkable statements, including acceptance criteria and explicit non-goals.
3. **Read the diff**: `git diff --merge-base origin/main`. Read surrounding code where needed.
4. **Check each requirement**: met / partly met / not met / can't tell, with the file and line that shows it.
5. **Check tests**: is each requirement covered by a test that would fail without the change, and does it run offline on the mock provider?
6. **Check the docs stay in step**: a pattern change should match its `docs/book/` chapter and `PATTERNS.md`; a new design choice needs a `DECISIONS.md` entry.
7. **Flag scope creep**: changed behaviour no requirement asked for.
8. **Report** in this shape:

```
Spec: <link or path>
| Requirement | Status | Evidence |
|---|---|---|
Untested requirements: …
Docs out of step: …
Scope creep: …
Verdict: ready / needs work
```

Do not edit code during the review.
