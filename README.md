# miniharness

A tiny agent harness built from scratch to learn design patterns
([refactoring.guru](https://refactoring.guru/design-patterns)) while building
something real: an LLM tool-use loop with providers, tools, middleware,
tracing, checkpoints and sub-agents.

## Setup

Uses [uv](https://docs.astral.sh/uv/) for Python, dependencies and the venv.

```bash
uv sync                # creates .venv and installs everything from uv.lock
cp .env.example .env   # add your OPENROUTER_API_KEY; for Anthropic, `ant auth login` or ANTHROPIC_API_KEY
uv run pytest          # uses the mock provider: free and offline
uv run examples/hello.py                 # flags mapped onto the Harness facade
uv run examples/hello.py -m anthropic:claude-haiku-5-5
uv run examples/hello.py --rewind "Write a haiku to haiku.txt"   # asks before writing, undoes after
uv run examples/hello.py --cache --budget 0.01                  # dev cache + spend limit
uv run examples/hello.py -m anthropic --fallback openrouter      # fall back on outages
uv run examples/hello.py --read-only "Write a haiku to haiku.txt"  # model can't see write tools
uv run examples/hello.py --trace run.jsonl                        # also write a JSONL event trace
uv run examples/hello.py --checkpoint run.json --budget 0.0001    # stops early; rerun to resume
uv run examples/hello.py --delegate "Ask the researcher what notes.txt says"  # read-only sub-agent
uv run examples/hello.py --stream "Explain undo in two sentences"  # print tokens as they arrive
uv run examples/stream.py --max-words 15 "Tell me a long story"    # pull the run with a for loop; stop early
uv run examples/team.py                                           # writer and reviewer via a mediator
uv run examples/hello.py --agent planner "What is (17 * 23) + 4?"  # plan first, then act
uv run examples/hello.py --agent reviewer                         # draft, review once, final answer
uv run examples/bridge.py -m openrouter -m anthropic              # every agent type × every provider
uv run python -m miniharness.trace run.jsonl --html report.html   # summarize a trace
```

From Python, the facade is the short way in:

```python
from dotenv import load_dotenv
from miniharness import Harness

load_dotenv(".env")
h = Harness("openrouter", budget=0.05, workspace="workspace", approve=True)
print(h.run("Write a haiku about undo to haiku.txt"))
print(h.report())   # calls, tokens, cost
h.rewind()          # undo the file changes

# The agent type and the provider vary independently (Bridge):
from miniharness import PlannerAgent
Harness("openrouter", agent_type=PlannerAgent).run("What is (17 * 23) + 4?")

# Your own providers go in your own registry; the built-in one stays untouched:
from miniharness.providers import OpenRouterProvider, default_registry
mine = default_registry.copy()
mine.add("cheap", lambda model="deepseek/deepseek-chat", **kw: OpenRouterProvider(model=model, **kw))
Harness("cheap", registry=mine).run("Hi")
```

Add dependencies with `uv add <pkg>` (or `uv add --dev <pkg>`), never `pip install`.

## Study book

[`docs/book/`](docs/book/README.md) is the project written up as a book to read: one chapter per stage,
telling what we built, what broke, what we decided and why, and what live runs taught us, plus an
epilogue with the cross-cutting lessons and open questions, and a cheat-sheet appendix.

## Layout

| File | What it is |
|---|---|
| `src/miniharness/harness.py` | `Harness`: one object that builds and runs a capable agent, every part still reachable (stage 16: Facade); `registry=` (Singleton → DI) |
| `src/miniharness/trace.py` | Trace tree + visitors: `CostSummary`, `HtmlReport` (stage 14: Visitor) |
| `src/miniharness/types.py` | Provider-neutral `Message`, `ToolCall`, `LLMResponse`; stream chunks `TextDelta`, `Completed` |
| `src/miniharness/agent.py` | The agent (stage 1: Template Method), with an injected provider (wires the default Toolbox it builds to its own bus); `iter_run()` (stage 15: Iterator); `first_state()` / `after_answer()` hooks (Bridge) |
| `src/miniharness/agent_types.py` | `PlannerAgent`, `ReviewerAgent`: agent types that run on any provider (bonus: Bridge) |
| `src/miniharness/lifecycle.py` | Agent lifecycle states: `start()` / `step()` (stage 9: State); generator `iter_step()` (stage 15); `Planning` state and the shared `model_call()` (Bridge) |
| `src/miniharness/providers/` | `Provider` protocol + OpenRouter, Anthropic, Mock (stage 2: Strategy); `create_provider()` registry (stage 3: Factory), an injectable `ProviderRegistry` with a `default_registry` (bonus: Singleton → DI); usage/budget/retry/cache wrappers (stage 6: Decorator); `FallbackChain` (stage 7); `LazyProvider` (stage 8: Proxy); `CircuitBreaker` (stage 9: State); `build_stack()` recipe (stage 16); `stream()` on every provider and wrapper, `streaming.py` helpers (stage 15: Iterator) |
| `src/miniharness/adapters/` | Our types ↔ OpenAI / Anthropic wire formats (stage 2: Adapter) |
| `src/miniharness/checkpoint.py` | `Checkpoint`: snapshot, save, load (stage 11: Memento); `Agent.fork()` (Prototype) |
| `src/miniharness/events.py` | Typed events + `EventBus` (stage 10: Observer); `TokenStreamed` (stage 15) |
| `src/miniharness/observers.py` | `ConsolePrinter`, `JsonlTracer` |
| `src/miniharness/prompts.py` | `SystemPromptBuilder` + `default_prompt()` director (stage 4: Builder) |
| `src/miniharness/team.py` | `Team` mediator: peers talk only through it (stage 13: Mediator) |
| `src/miniharness/tools/` | `Tool` classes, `ToolCommand`, and the `Toolbox` invoker with undo (stage 5: Command); `PolicyChain` permissions (stage 7: Chain of Responsibility); `ToolboxView` (stage 8: Proxy); `AgentTool` (stage 12: Composite); read-only calls of one turn run together with `Toolbox(max_workers=...)` (bonus: concurrent tools) |
| `tests/test_singleton.py` | A textbook Singleton kept as a specimen, next to the DI that replaced it |
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
| 12 | Sub-agents as tools (`AgentTool`); trees with derived side effects | Composite ✅ |
| 13 | Peer team (writer ↔ reviewer) routed by a `Team` mediator | Mediator ✅ |
| 14 | Trace tree from events; cost summary and HTML report | Visitor ✅ |
| 15 | Streaming tokens and events; `for event in agent.iter_run(task)` | Iterator ✅ |
| 16 | `Harness("openrouter").run(task)` hides the wiring; `build_stack()` recipe | Facade ✅ |
| + | Agent types × providers: `PlannerAgent`, `ReviewerAgent` on any provider | Bridge ✅ |
| + | Global registry → injected `ProviderRegistry`; agents wire what they build | Singleton (and why to avoid it) ✅ |
| + | Read-only tool calls of one turn run together; side effects stay in order | No new pattern: concurrency on top of Command ✅ |
| + | Per-request model choice (cheap vs strong) | Strategy, part 2 |

## Rules of the road

1. **Naive first, then refactor.** Feel the smell before applying the fix.
2. **Mock first.** `MockProvider` keeps tests deterministic and free.
3. **Journal everything** in `PATTERNS.md`: the problem, the alternatives, the cost.
   Record design choices in `DECISIONS.md`, including the small ones.
4. **Notice where Python dissolves a pattern** (functions as Strategy/Command, generators as Iterator).
5. **No speculative patterns.** A real need (a second provider, a hard-to-write test) must come first.

## Credits

The pattern catalogue this project learned from is
[refactoring.guru](https://refactoring.guru/design-patterns) by Alexander Shvets, and each book
chapter links to the page for its pattern. Everything here is written from scratch: no text,
code examples or illustrations are copied from the site.

If you add material from refactoring.guru, follow its
[Content Usage Policy](https://refactoring.guru/content-usage-policy): link to the exact page it
came from, quote only short passages (never a substantial part of an article), and use no more
than 10 of its illustrations in total. For anything beyond that, ask the authors first at
support@refactoring.guru.
