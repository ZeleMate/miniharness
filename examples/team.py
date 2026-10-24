"""A writer and a reviewer that only talk through a Team mediator.

    uv run examples/team.py
    uv run examples/team.py "Write a two-sentence product description for a rubber duck."
"""

import argparse

from dotenv import load_dotenv

from miniharness import Agent
from miniharness.events import EventBus
from miniharness.observers import ConsolePrinter
from miniharness.prompts import SystemPromptBuilder
from miniharness.providers import BudgetGuard, UsageTracker, create_provider
from miniharness.team import Team
from miniharness.tools import Toolbox


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--model", default="openrouter")
    parser.add_argument("--budget", type=float, default=0.05)
    parser.add_argument("task", nargs="?", default="Write a haiku about the undo button.")
    args = parser.parse_args()

    tracker = UsageTracker(create_provider(args.model))
    provider = BudgetGuard(tracker, limit_usd=args.budget)  # one budget for the whole team
    events = EventBus()
    events.subscribe(ConsolePrinter())

    writer = Agent(
        provider,
        system_prompt=SystemPromptBuilder()
        .identity("You are a writer on a two-person team.")
        .instructions(
            "Send every draft to the reviewer with send_message.",
            "Send only the draft itself, nothing else.",
            "When the reviewer gives feedback, revise and send the new draft.",
            "After sending, reply with one short sentence.",
        )
        .build(),
        tools=Toolbox([]),
        events=events,
    )
    reviewer = Agent(
        provider,
        system_prompt=SystemPromptBuilder()
        .identity("You are a demanding but fair reviewer on a two-person team.")
        .instructions(
            "If a draft has a real flaw, send one concrete improvement to the writer with send_message.",
            "Check every requirement in the original task literally (count words if asked).",
            "Ask for at most one revision. When the draft meets every requirement, call approve.",
            "After using a tool, reply with one short sentence.",
        )
        .build(),
        tools=Toolbox([]),
        events=events,
    )
    team = Team(
        members={"writer": writer, "reviewer": reviewer},
        routes={"writer": ["reviewer"], "reviewer": ["writer"]},
        finishers={"reviewer"},
        max_turns=6,
    )

    result = team.run("writer", args.task)
    print(f"\n{result}\n")
    total = tracker.total
    cost = "unknown" if total.cost_usd is None else f"${total.cost_usd:.6f}"
    print(f"{len(team.log)} message(s) routed, {len(tracker.calls)} model call(s), {cost}")


if __name__ == "__main__":
    main()
