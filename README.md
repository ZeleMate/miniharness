# miniharness

A small LLM agent harness built from scratch to learn the classic design patterns by applying them to a
real system: a tool-use loop with pluggable providers, sandboxed tools with undo, permission policies,
retries and budgets, tracing, checkpoints, streaming and sub-agents.

Each pattern was added only when the code needed it. The [study book](docs/book/README.md) tells that
story chapter by chapter, and [`DECISIONS.md`](DECISIONS.md) records every design decision with its
trade-offs.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run pytest                     # offline: uses the mock provider
cp .env.example .env              # add OPENROUTER_API_KEY, or use `ant auth login` for Anthropic
uv run examples/hello.py "What is (17 * 23) + 4?"
```

From Python, the `Harness` facade builds and runs a fully wired agent:

```python
from dotenv import load_dotenv
from miniharness import Harness, PlannerAgent

load_dotenv()
h = Harness("openrouter", budget=0.05, workspace="workspace", approve=True)
print(h.run("Write a haiku about undo to haiku.txt"))
print(h.report())  # calls, tokens, cost
h.rewind()  # undo the file changes

# Agent types and providers vary independently
Harness("anthropic", agent_type=PlannerAgent).run("What is (17 * 23) + 4?")
```

### Example flags

`examples/hello.py` exposes most features as flags:

| Flag | Effect |
|---|---|
| `-m anthropic:claude-haiku-5-5` | Choose `provider[:model]` |
| `--fallback openrouter` | Fall back to another provider on outages |
| `--budget 0.01`, `--cache` | Spending limit; replay identical requests from a dev cache |
| `--read-only` | Hide tools that change anything |
| `--rewind` | Ask before writing, undo all file changes afterwards |
| `--stream` | Print tokens as they arrive |
| `--trace run.jsonl` | Write a JSONL event trace |
| `--checkpoint run.json` | Autosave; rerun to resume an unfinished run |
| `--delegate` | Add a read-only sub-agent |
| `--agent planner` / `--agent reviewer` | Plan first, or draft and self-review |

Also see `examples/stream.py` (iterate over a run and stop early), `examples/team.py` (writer and
reviewer agents through a mediator) and `examples/bridge.py` (every agent type on every provider).
Summarize a trace with `uv run python -m miniharness.trace run.jsonl --html report.html`.

## Roadmap

Only add a pattern once you feel the pain it solves.

| # | Stage | Pattern(s) |
|---|---|---|
| 1 | Core loop with overridable steps | Template Method (scaffolded) |
| 2 | OpenRouter / Anthropic / Mock providers | Strategy, Adapter |
| 3 | Providers from `"provider:model"` specs | Factory (Abstract Factory deferred, D14) |
| 4 | System prompt from sections (stable → volatile) | Builder |
| 5 | Tool calls as objects with undo; sandboxed file tools | Command |
| 6 | Retry, dev cache, cost tracking, `BudgetGuard` | Decorator |
| 7 | Tool-call policy chain with human approval; model fallbacks | Chain of Responsibility |
| 8 | Lazy providers; read-only toolbox views | Proxy |
| 9 | Circuit breaker; agent lifecycle with `step()` | State |
| 10 | Typed events on a shared bus; live console + JSONL trace | Observer |
| 11 | Checkpoint, rewind (with files), save/resume, fork | Memento, Prototype |
| 12 | Sub-agents as tools (`AgentTool`); trees with derived side effects | Composite |
| 13 | Peer team (writer ↔ reviewer) routed by a `Team` mediator | Mediator |
| 14 | Trace tree from events; cost summary and HTML report | Visitor |
| 15 | Streaming tokens and events; `for event in agent.iter_run(task)` | Iterator |
| 16 | `Harness("openrouter").run(task)` hides the wiring; `build_stack()` recipe | Facade |
| + | Agent types × providers: `PlannerAgent`, `ReviewerAgent` on any provider | Bridge |
| + | Global registry → injected `ProviderRegistry`; agents wire what they build | Singleton (and why to avoid it) |
| + | Read-only tool calls of one turn run together; side effects stay in order | No new pattern: concurrency on top of Command |

Next: per-request model choice (cheap vs strong), Strategy part 2.

## Layout

All under `src/miniharness/`. [`PATTERNS.md`](PATTERNS.md) has a short journal entry per pattern.

| Path | Contents |
|---|---|
| `harness.py` | `Harness` facade |
| `agent.py`, `agent_types.py`, `lifecycle.py` | Agent loop, agent types, lifecycle states |
| `providers/` | Provider protocol, OpenRouter / Anthropic / mock, registry, wrappers, fallbacks, circuit breaker |
| `adapters/` | Conversion to and from the OpenAI and Anthropic wire formats |
| `tools/` | Tools, toolbox with undo, permission policies, read-only views, sub-agent tool |
| `prompts.py` | System prompt builder |
| `events.py`, `observers.py`, `trace.py` | Event bus, console and JSONL observers, trace reports |
| `checkpoint.py`, `team.py` | Checkpoints; multi-agent team

## Development

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest --cov               # 95% coverage floor
```

[CI](.github/workflows/ci.yml) runs these on Python 3.12–3.14, plus pip-audit, Semgrep, gitleaks over
the full history, and actionlint and zizmor on the workflows. CI-only tools are locked separately in
[`.github/tools`](.github/tools/pyproject.toml).

## Credits

The pattern catalogue comes from [refactoring.guru](https://refactoring.guru/design-patterns) by
Alexander Shvets, and each book chapter links to its pattern's page. All text and code here are
original. Any material added from the site must follow its
[content usage policy](https://refactoring.guru/content-usage-policy).

## License

[MIT](LICENSE)
