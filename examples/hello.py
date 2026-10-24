"""Run the agent against a real model.

    uv run examples/hello.py                                 # OpenRouter, default model
    uv run examples/hello.py -m anthropic
    uv run examples/hello.py -m openrouter:qwen/qwen3-coder "your task"
    uv run examples/hello.py --rewind "Write a haiku about undo to haiku.txt"
    uv run examples/hello.py --cache --budget 0.01
    uv run examples/hello.py --yes "Write a haiku to haiku.txt"    # approve file writes
    uv run examples/hello.py -m anthropic:claude-haiku-5-5 --fallback openrouter
"""

import argparse
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from miniharness import Agent
from miniharness.prompts import default_prompt
from miniharness.providers import (
    BudgetGuard,
    DiskCache,
    FallbackChain,
    Retry,
    UsageTracker,
    available_providers,
    create_provider,
)
from miniharness.tools import (
    AllowReadOnly,
    AskBeforeSideEffects,
    MaxCalls,
    PolicyChain,
    Toolbox,
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
    parser.add_argument("--yes", action="store_true", help="approve every tool call that asks")
    parser.add_argument("--rewind", action="store_true", help="undo all file changes after the run")
    parser.add_argument("task", nargs="?", default="What is (17 * 23) + 4? Also, what time is it in UTC?")
    args = parser.parse_args()

    base = create_provider(args.model)
    if args.fallback:
        base = FallbackChain([base, create_provider(args.fallback)])
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
    toolbox = Toolbox(default_tools(workspace), policy=policy)
    agent = Agent(provider=provider, system_prompt=system_prompt, tools=toolbox)
    print(f"[{type(base).__name__} / {provider.model}]")
    answer = agent.run(args.task)

    for m in agent.messages[2:]:
        if m.role == "tool":
            print(f"  tool -> {m.content}")
        for tc in m.tool_calls:
            print(f"  call {tc.name}({tc.arguments})")
    print(f"\n{answer}")

    for call, decision in toolbox.denied:
        print(f"  denied {call.name}: {decision.reason} (by {decision.policy})")
    if isinstance(base, FallbackChain) and base.failures:
        for provider, why in base.failures:
            print(f"  fell back from {provider.model}: {why}")

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
