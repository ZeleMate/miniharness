# Review rubric

Used by AI reviewers (the Claude review workflow, the `code-reviewer` subagent) and for self-review. Ruff, mypy, the 95% coverage gate, Semgrep, pip-audit, Gitleaks, actionlint and zizmor already run in CI; do not comment on what they enforce.

Report only findings you can point to in the diff, with a concrete suggested change. Say "no findings" when there are none.

## 1. Does it do what was asked?

- Find the linked issue, PR description or `DECISIONS.md` entry. List each requirement and whether the diff meets it.
- A new design choice needs a `DECISIONS.md` entry; a pattern change should match its book chapter and `PATTERNS.md`.
- Flag scope creep.

## 2. Correctness

- Logic errors, unhandled `None`, exceptions swallowed or turned into silent defaults.
- Undo: every tool that changes state can be undone, and `rewind()` restores it.
- Async and concurrent tools: missing `await`, shared mutable state, ordering assumptions.
- Tests exercise failure paths (denied calls, provider errors, budget exhaustion), not just the happy path. They run offline on the mock provider.

## 3. Security

- File tools go through `resolve_in_workspace`; no new path handling bypasses it.
- New tools are covered by the policy chain, and anything that writes or runs is not `ALLOW` by default.
- Model and tool output are treated as untrusted data, never as instructions, shell input or code.
- Budgets and iteration limits apply to new loops, retries and sub-agents.
- Nothing writes API keys, `.env` contents or other secrets to traces, checkpoints, logs or prompts.
- New dependencies are real, maintained, needed and MIT-compatible.
- CI changes: permissions widened, actions not pinned to a full SHA, untrusted `${{ }}` in `run:`.

## 4. Agentic risks (OWASP Top 10 for LLM Applications 2026, OWASP Agentic Top 10)

Check these against `docs/THREAT_MODEL.md`:

- New or widened tool permissions: LLM03 Excessive Agency, ASI02 Tool Misuse.
- Tool output steering the agent: LLM01 Prompt Injection, ASI01 Agent Goal Hijack.
- Model output used without validation: LLM10 Improper Output Handling.
- Sub-agents inheriting more tools or budget than they need: ASI03, ASI08 Cascading Failures.
- Irreversible actions without approval: ASI09.

## Severity

- **blocker**: wrong behaviour, security issue, lost undo.
- **should-fix**: missing failure-path tests, unclear error handling.
- **nit**: only when it materially affects readability.
