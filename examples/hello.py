"""Run the agent against a real model.

    uv run examples/hello.py                                 # OpenRouter, default model
    uv run examples/hello.py -m anthropic
    uv run examples/hello.py -m openrouter:qwen/qwen3-coder "your task"
    uv run examples/hello.py --rewind "Write a haiku about undo to haiku.txt"
    uv run examples/hello.py --cache --budget 0.01
    uv run examples/hello.py --yes "Write a haiku to haiku.txt"    # approve file writes
    uv run examples/hello.py -m anthropic:claude-haiku-5-5 --fallback openrouter
    uv run examples/hello.py --read-only "Write a haiku to haiku.txt"  # model can't see write_file
    uv run examples/hello.py --trace run.jsonl                          # also write a JSONL trace
    uv run examples/hello.py --checkpoint run.json --budget 0.0001      # stops; rerun to resume
    uv run examples/hello.py --delegate "Ask the researcher what notes.txt says"
"""

import argparse
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from miniharness import Agent
from miniharness.checkpoint import Checkpoint
from miniharness.events import EventBus, RunFinished, StateChanged
from miniharness.observers import ConsolePrinter, JsonlTracer
from miniharness.prompts import default_prompt
from miniharness.providers import (
    BudgetGuard,
    CircuitBreaker,
    DiskCache,
    FallbackChain,
    Retry,
    UsageTracker,
    available_providers,
    create_provider,
    lazy_provider,
)
from miniharness.tools import (
    AgentTool,
    AllowReadOnly,
    AskBeforeSideEffects,
    MaxCalls,
    PolicyChain,
    Toolbox,
    ToolboxView,
    default_tools,
)
from miniharness.types import ToolCall


def terminal_approver(call: ToolCall) -> bool:
    try:
        answer = input(f"  allow {call.name}({call.arguments})? [y/N] ")
    except EOFError:  # no terminal attached: treat as "no"
        return False
    return answer.strip().lower() in ("y", "yes")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-m", "--model", default="openrouter",
        help=f"provider[:model], provider one of: {', '.join(available_providers())}",
    )
    parser.add_argument("--budget", type=float, default=0.05, help="stop after spending this many USD")
    parser.add_argument("--cache", action="store_true", help="replay identical requests from .cache/llm")
    parser.add_argument("--fallback", help="provider[:model] to use if the main one fails or refuses")
    parser.add_argument("--trace", help="append every event to this JSONL file")
    parser.add_argument("--checkpoint", help="autosave here; if it exists, resume the unfinished run")
    parser.add_argument("--delegate", action="store_true", help="add a read-only 'researcher' sub-agent")
    parser.add_argument("--read-only", action="store_true", help="hide tools that change anything")
    parser.add_argument("--yes", action="store_true", help="approve every tool call that asks")
    parser.add_argument("--rewind", action="store_true", help="undo all file changes after the run")
    parser.add_argument("task", nargs="?", default="What is (17 * 23) + 4? Also, what time is it in UTC?")
    args = parser.parse_args()

    base = create_provider(args.model)  # built now: a bad config fails at startup
    if args.fallback:
        # Lazy: the backup is only built (and its key only needed) if the main one fails
        # The breaker stops retrying a failing main provider on every turn
        base = FallbackChain([CircuitBreaker(base), lazy_provider(args.fallback)])
    tracker = UsageTracker(base)
    provider = Retry(BudgetGuard(tracker, limit_usd=args.budget))
    if args.cache:
        provider = DiskCache(provider, ".cache/llm")
    system_prompt = (
        default_prompt()
        .instructions("Answer in plain text. No LaTeX or markdown math.")
        .environment(date=date.today().isoformat(), cwd=os.getcwd())
        .build()
    )
    workspace = Path("workspace")
    workspace.mkdir(exist_ok=True)
    policy = PolicyChain(
        [MaxCalls("write_file", 5), AllowReadOnly(), AskBeforeSideEffects()],
        approver=(lambda call: True) if args.yes else terminal_approver,
    )
    events = EventBus()
    events.subscribe(ConsolePrinter())
    if args.trace:
        events.subscribe(JsonlTracer(args.trace))
    toolbox = Toolbox(default_tools(workspace), policy=policy, events=events)
    if args.delegate:
        # Same provider (and budget); can only read; reports on the same event bus
        researcher = Agent(
            provider=provider,
            system_prompt=default_prompt().instructions("Read files to answer. Reply with a short summary.").build(),
            tools=ToolboxView.read_only(toolbox),
            events=events,
        )
        toolbox.add(AgentTool("researcher", "Reads files in the workspace and summarizes them.", researcher))
    tools = ToolboxView.read_only(toolbox) if args.read_only else toolbox
    agent = Agent(provider=provider, system_prompt=system_prompt, tools=tools, events=events)
    print(f"[{type(base).__name__} / {provider.model}]")
    if args.checkpoint:
        saved = Path(args.checkpoint)

        def autosave(event):
            if isinstance(event, StateChanged) and not agent.done:
                agent.checkpoint().save(saved)
            elif isinstance(event, RunFinished) and event.state == "done":
                saved.unlink(missing_ok=True)  # finished: next run starts fresh

        resume = Checkpoint.load(saved) if saved.exists() else None
        events.subscribe(autosave)
    else:
        resume = None

    if resume is not None:
        print(f"  resuming from {args.checkpoint} ({resume.model_calls} model call(s) already made)")
        agent.restore(resume, files=False)  # a new process: its Toolbox history is gone
        while not agent.done:
            agent.step()
        answer = agent.state.answer
    else:
        answer = agent.run(args.task)  # the ConsolePrinter shows progress live
    print(f"\n{answer}")

    if isinstance(base, FallbackChain) and base.failures:
        for link, why in base.failures:
            print(f"  fell back from {link.model}: {why}")

    total = tracker.total
    cost = "unknown" if total.cost_usd is None else f"${total.cost_usd:.6f}"
    line = f"\n{len(tracker.calls)} model call(s), {total.input_tokens} in / {total.output_tokens} out tokens, {cost}"
    if args.cache:
        line += f", cache {provider.hits} hit(s) / {provider.misses} miss(es)"
    print(line)

    changes = [c for c in toolbox.history if c.tool.side_effects]
    if changes:
        print(f"\n{len(changes)} change(s) in ./{workspace}/")
        if args.rewind:
            for command in toolbox.undo_all():
                print(f"  undid {command.tool.name}({command.call.arguments.get('path')})")


if __name__ == "__main__":
    main()
