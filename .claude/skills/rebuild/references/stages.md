# Stage map

Every stage is one commit on `main`. Rebuilding a stage starts from that commit's **parent**, which is not
always the previous stage (a few stages follow a docs or CI commit). The hashes below were checked against
`main`; resolve them with `git rev-parse <hash>` before use.

| Stage | Pattern(s) | Book chapter | Stage commit | Parent (start here) | Acceptance tests (from the stage commit) | `DECISIONS.md` section |
|---|---|---|---|---|---|---|
| 1 | Template Method (scaffold) | `01-the-naive-start.md` | `a9eab0f` | none (root commit) | `test_agent.py` | none; stage 1 has no entries |
| 2 | Strategy + Adapter | `02-strategy-and-adapter.md` | `5aae911` | `a4fccc3` | `test_agent.py`, `test_wire_format.py` | Stage 2, D1–D11 |
| 3 | Factory | `03-factory.md` | `0493e00` | `769398d` | `test_registry.py` | Stage 3, D12–D20 |
| 4 | Builder | `04-builder.md` | `8459a3d` | `0493e00` | `test_prompts.py` | Stage 4, D21–D28 |
| 5 | Command | `05-command.md` | `731fcfa` | `8459a3d` | `test_agent.py`, `test_tools.py`, `test_wire_format.py` | Stage 5, D29–D40 |
| 6 | Decorator | `06-decorator.md` | `8340d1b` | `731fcfa` | `test_wrappers.py` | Stage 6, D41–D54 |
| 7 | Chain of Responsibility | `07-chain-of-responsibility.md` | `c15752d` | `8340d1b` | `test_policy.py`, `test_tools.py`, `test_wrappers.py` | Stage 7, D55–D67 |
| 8 | Proxy | `08-proxy.md` | `36cd5fc` | `c15752d` | `test_proxies.py` | Stage 8, D68–D78 |
| 9 | State | `09-state.md` | `e5c883c` | `36cd5fc` | `test_state.py` | Stage 9, D79–D92 |
| 10 | Observer | `10-observer.md` | `3636a14` | `e5c883c` | `test_events.py` | Stage 10, D93–D104 |
| 11 | Memento + Prototype | `11-memento-and-prototype.md` | `ebe9b0f` | `3636a14` | `test_memento.py` | Stage 11, D105–D118 |
| 12 | Composite | `12-composite.md` | `25f45e8` | `ebe9b0f` | `test_composite.py`, `test_events.py` | Stage 12, D119–D132 |
| 13 | Mediator | `13-mediator.md` | `b239ce7` | `a4b3207` | `test_team.py` | Stage 13, D133–D144 |
| 14 | Visitor | `14-visitor.md` | `4ec7d73` | `b239ce7` | `test_trace.py` | Stage 14, D145–D155 |
| 15 | Iterator | `15-iterator.md` | `68a7852` | `4ec7d73` | `test_iterator.py`, `test_streaming.py` | Stage 15, D156–D172 |
| 16 | Facade | `16-facade.md` | `343ec87` | `68a7852` | `test_facade.py` | Stage 16, D173–D187 |
| bridge | Bridge | `17-bridge.md` | `dba6d7f` | `343ec87` | `test_bridge.py` | Bonus stage: Bridge, D188–D201 |
| singleton | Singleton → dependency injection | `18-singleton-to-di.md` | `fa9377d` | `dba6d7f` | `test_events.py`, `test_facade.py`, `test_registry.py`, `test_singleton.py` | Bonus stage: Singleton → DI, D202–D211 |
| concurrency | Concurrent tools (no new pattern) | `19-concurrent-tools.md` | `1aa7f47` | `744039c` | `test_concurrency.py` | Bonus stage: Concurrent tools, D215–D223 |

Accepted aliases: "stage 17" or "Bridge" → `bridge`; "stage 18", "Singleton" or "DI" → `singleton`;
"stage 19", "concurrency" or "parallel tools" → `concurrency`. A pattern name maps to the stage that
introduces it (Memento and Prototype → 11).

## Notes per stage

- **Stage 1** has no parent, so there is nothing to rebuild from. Offer the Template Method **Try it**
  exercise in `PATTERNS.md` instead (the `tutor` skill covers it).
- **Stage 2** starts from a commit that adds characterization tests for the wire format (D1). Those tests
  already pass at the parent and must keep passing: the refactor may change structure, not payloads.
- **Stages 5, 7, 12 and singleton** change existing test files as well as adding new ones. The acceptance
  run uses the stage commit's version of every listed file.
- **Stages 13 and concurrency** start after a docs or hardening commit; the parent's `src/` is the previous
  stage's code plus those fixes.
- **Early stages predate ruff, mypy and the CI pipeline** (D224). Their `pyproject.toml` has only `pytest` in
  the dev group, and `uv.lock` differs from `main`'s, so `uv sync` is needed after creating the worktree.
  Lint and type-check the learner's code only if they ask; the acceptance check is `pytest`.

## Commands

```bash
# list exactly which test files the stage commit added or changed
git diff --name-status <parent> <commit> -- tests/

# the reference solution, for the final comparison only
git diff <parent> <commit> --stat -- src/
git diff <parent> <commit> -- src/
```
