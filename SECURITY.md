# Security policy

miniharness is a learning project, maintained by one person. Only the latest commit on `main` is supported.

## Reporting a vulnerability

Please do not open a public issue. Report it privately through GitHub: **Security → Report a vulnerability** on this repository.

Include what you found, how to reproduce it, and the impact you expect. You will get an acknowledgement within 14 days, and confirmed issues are fixed or documented with a mitigation. Credit goes in the fix's commit and in `DECISIONS.md` unless you prefer otherwise.

## Scope

In scope: the `miniharness` package, the examples, and the CI pipeline.

Because miniharness runs LLM agents with tools, these count as vulnerabilities even when the root cause is model behaviour rather than a code bug:

- a tool reading or writing outside the workspace (`resolve_in_workspace` bypasses, symlink tricks);
- a tool call that runs without passing the permission policy chain, or an `ASK` verdict resolved without the approver;
- prompt injection through tool output, files or sub-agent results that makes the harness take actions it would otherwise refuse;
- budget or iteration limits that can be bypassed, leading to unbounded spend;
- API keys or other secrets leaking into traces, checkpoints, logs or model prompts.

Out of scope: weaknesses in the model providers themselves, and anything that needs an attacker who can already edit your local `.env` or source code.
