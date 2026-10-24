"""Run the agent against a real model.

    uv run examples/hello.py                                 # OpenRouter, default model
    uv run examples/hello.py -m anthropic
    uv run examples/hello.py -m openrouter:qwen/qwen3-coder "your task"
    uv run examples/hello.py --rewind "Write a haiku about undo to haiku.txt"
"""

import argparse
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from miniharness import Agent
from miniharness.prompts import default_prompt
from miniharness.providers import available_providers, create_provider
from miniharness.tools import Toolbox, default_tools


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-m", "--model", default="openrouter",
        help=f"provider[:model], provider one of: {', '.join(available_providers())}",
    )
    parser.add_argument("--rewind", action="store_true", help="undo all file changes after the run")
    parser.add_argument("task", nargs="?", default="What is (17 * 23) + 4? Also, what time is it in UTC?")
    args = parser.parse_args()

    provider = create_provider(args.model)
    system_prompt = (
        default_prompt()
        .instructions("Answer in plain text. No LaTeX or markdown math.")
        .environment(date=date.today().isoformat(), cwd=os.getcwd())
        .build()
    )
    workspace = Path("workspace")
    workspace.mkdir(exist_ok=True)
    toolbox = Toolbox(default_tools(workspace))
    agent = Agent(provider=provider, system_prompt=system_prompt, tools=toolbox)
    print(f"[{type(provider).__name__} / {provider.model}]")
    answer = agent.run(args.task)

    for m in agent.messages[2:]:
        if m.role == "tool":
            print(f"  tool -> {m.content}")
        for tc in m.tool_calls:
            print(f"  call {tc.name}({tc.arguments})")
    print(f"\n{answer}")

    changes = [c for c in toolbox.history if c.tool.side_effects]
    if changes:
        print(f"\n{len(changes)} change(s) in ./{workspace}/")
        if args.rewind:
            for command in toolbox.undo_all():
                print(f"  undid {command.tool.name}({command.call.arguments.get('path')})")


if __name__ == "__main__":
    main()
