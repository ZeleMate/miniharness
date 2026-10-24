# miniharness

A tiny agent harness built from scratch to learn design patterns
([refactoring.guru](https://refactoring.guru/design-patterns)) while building
something real: an LLM tool-use loop with providers, tools, middleware,
tracing, checkpoints and sub-agents.

## Setup

Uses [uv](https://docs.astral.sh/uv/) for Python, dependencies and the venv.

```bash
uv sync                # creates .venv and installs everything from uv.lock
cp .env.example .env   # add your OPENROUTER_API_KEY (and optionally ANTHROPIC_API_KEY)
uv run pytest          # uses the mock provider: free and offline
uv run examples/hello.py
uv run examples/hello.py -m anthropic:claude-haiku-5-5
uv run examples/hello.py --rewind "Write a haiku to haiku.txt"   # asks before writing, undoes after
uv run examples/hello.py --cache --budget 0.01                  # dev cache + spend limit
uv run examples/hello.py -m anthropic --fallback openrouter      # fall back on outages
uv run examples/hello.py --read-only "Write a haiku to haiku.txt"  # model can't see write tools
uv run examples/hello.py --trace run.jsonl                        # also write a JSONL event trace
uv run examples/hello.py --checkpoint run.json --budget 0.0001    # stops early; rerun to resume
uv run examples/hello.py --delegate "Ask the researcher what notes.txt says"  # read-only sub-agent
```

Add dependencies with `uv add <pkg>` (or `uv add --dev <pkg>`), never `pip install`.

## Layout

| File | What it is |
|---|---|
| `src/miniharness/types.py` | Provider-neutral `Message`, `ToolCall`, `LLMResponse` |
| `src/miniharness/agent.py` | The agent (stage 1: Template Method), with an injected provider |
| `src/miniharness/lifecycle.py` | Agent lifecycle states: `start()` / `step()` (stage 9: State) |
| `src/miniharness/providers/` | `Provider` protocol + OpenRouter, Anthropic, Mock (stage 2: Strategy); `create_provider()` registry (stage 3: Factory); usage/budget/retry/cache wrappers (stage 6: Decorator); `FallbackChain` (stage 7); `LazyProvider` (stage 8: Proxy); `CircuitBreaker` (stage 9: State) |
| `src/miniharness/adapters/` | Our types ↔ OpenAI / Anthropic wire formats (stage 2: Adapter) |
| `src/miniharness/checkpoint.py` | `Checkpoint`: snapshot, save, load (stage 11: Memento); `Agent.fork()` (Prototype) |
| `src/miniharness/events.py` | Typed events + `EventBus` (stage 10: Observer) |
| `src/miniharness/observers.py` | `ConsolePrinter`, `JsonlTracer` |
| `src/miniharness/prompts.py` | `SystemPromptBuilder` + `default_prompt()` director (stage 4: Builder) |
| `src/miniharness/tools/` | `Tool` classes, `ToolCommand`, and the `Toolbox` invoker with undo (stage 5: Command); `PolicyChain` permissions (stage 7: Chain of Responsibility); `ToolboxView` (stage 8: Proxy);  (stage 12: Composite) |
| `DECISIONS.md` | Architecture decision log: options, trade-offs, open questions |
| `PATTERNS.md` | Your learning journal |

## Roadmap

Only add a pattern once you feel the pain it solves.

| # | Stage | Pattern(s) |
|---|---|---|
| 1 | Core loop with overridable steps | Template Method ✅ (scaffolded) |
| 2 | OpenRouter / Anthropic / Mock providers | Strategy, Adapter ✅ |
| 3 | Providers from `"provider:model"` specs | Factory ✅ (Abstract Factory deferred, D14) |
| 4 | System prompt from sections (stable → volatile) | Builder ✅ |
| 5 | Tool calls as objects with undo; sandboxed file tools | Command ✅ |
| 6 | Retry, dev cache, cost tracking, `BudgetGuard` | Decorator ✅ |
| 7 | Tool-call policy chain with human approval; model fallbacks | Chain of Responsibility ✅ |
| 8 | Lazy providers; read-only toolbox views | Proxy ✅ |
| 9 | Circuit breaker; agent lifecycle with `step()` | State ✅ |
| 10 | Typed events on a shared bus; live console + JSONL trace | Observer ✅ |
| 11 | Checkpoint, rewind (with files), save/resume, fork | Memento, Prototype ✅ |
| 12 | Sub-agents as tools (); trees with derived side effects | Composite ✅ |
| 13 | Coordinator routing between agents | Mediator |
| 14 | Cost/HTML/JSON over the trace tree | Visitor |
| 15 | Streaming tokens and events | Iterator |
| 16 | `Agent("task").run()` hides everything | Facade |
| + | Agent types × providers | Bridge |
| + | Global registry → dependency injection | Singleton (and why to avoid it) |
| + | Per-request model choice (cheap vs strong) | Strategy, part 2 |

## Rules of the road

1. **Naive first, then refactor.** Feel the smell before applying the fix.
2. **Mock first.** `MockProvider` keeps tests deterministic and free.
3. **Journal everything** in `PATTERNS.md`: the problem, the alternatives, the cost.
   Record design choices in `DECISIONS.md`, including the small ones.
4. **Notice where Python dissolves a pattern** (functions as Strategy/Command, generators as Iterator).
5. **No speculative patterns.** A real need (a second provider, a hard-to-write test) must come first.
