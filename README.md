# miniharness

A tiny agent harness built from scratch to learn design patterns
([refactoring.guru](https://refactoring.guru/design-patterns)) while building
something real: an LLM tool-use loop with providers, tools, middleware,
tracing, checkpoints and sub-agents.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env   # add your OPENROUTER_API_KEY (and optionally ANTHROPIC_API_KEY)
pytest                 # uses the mock provider: free and offline
python examples/hello.py
python examples/hello.py --provider anthropic
```

## Layout

| File | What it is |
|---|---|
| `src/miniharness/types.py` | Provider-neutral `Message`, `ToolCall`, `LLMResponse` |
| `src/miniharness/agent.py` | The loop (stage 1: Template Method) |
| `src/miniharness/llm.py` | **Naive** provider code: one big `if/elif`. Your first refactor target |
| `src/miniharness/tools.py` | **Naive** global tool registry |
| `PATTERNS.md` | Your learning journal |

## Roadmap

Only add a pattern once you feel the pain it solves.

| # | Stage | Pattern(s) |
|---|---|---|
| 1 | Core loop with overridable steps | Template Method ✅ (scaffolded) |
| 2 | OpenRouter / Anthropic / Mock providers | Strategy, Adapter |
| 3 | Providers from config | Factory Method, Abstract Factory |
| 4 | Fluent request construction | Builder |
| 5 | Tool calls as objects with undo and replay | Command |
| 6 | Retry, dev cache, cost tracking, `BudgetGuard` | Decorator |
| 7 | Model fallbacks; permission → rate limit → guardrail → approval | Chain of Responsibility |
| 8 | Sandboxed or lazily loaded tools; caching proxy | Proxy |
| 9 | `Idle → Thinking → AwaitingTool → AwaitingHuman → Done` | State |
| 10 | `on_token`, `on_tool_call` and `on_error` hooks | Observer |
| 11 | Checkpoint, rewind, fork; clone agent configs | Memento, Prototype |
| 12 | Agents as tools; sub-agent trees | Composite |
| 13 | Coordinator routing between agents | Mediator |
| 14 | Cost/HTML/JSON over the trace tree | Visitor |
| 15 | Streaming tokens and events | Iterator |
| 16 | `Agent("task").run()` hides everything | Facade |
| + | Agent types × providers | Bridge |
| + | Global registry → dependency injection | Singleton (and why to avoid it) |
| + | Per-request model choice (cheap vs strong) | Strategy, part 2 |

## Rules of the road

1. **Naive first, then refactor.** Feel the smell before applying the fix.
2. **Mock first.** `MockLLM` keeps tests deterministic and free.
3. **Journal everything** in `PATTERNS.md`: the problem, the alternatives, the cost.
4. **Notice where Python dissolves a pattern** (functions as Strategy/Command, generators as Iterator).
5. **No speculative patterns.** A real need (a second provider, a hard-to-write test) must come first.
