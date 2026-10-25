"""Bridge: run the same task with every agent type on every provider you name.

    uv run examples/bridge.py                                         # 3 agent types on OpenRouter
    uv run examples/bridge.py -m openrouter -m openrouter:qwen/qwen3-coder
    uv run examples/bridge.py -m anthropic "What is (17 * 23) + 4?"

The grid is agent types × providers, but there's no class per cell: each
row is one `agent_type`, each column one `model`, and `Harness` joins them.
A cell that fails (a bad key, a budget) is reported and the grid carries on.
"""

import argparse

from dotenv import load_dotenv

from miniharness import Agent, Harness, PlannerAgent, ReviewerAgent

AGENT_TYPES = [Agent, PlannerAgent, ReviewerAgent]


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--model", action="append", help="provider[:model]; repeat for more columns")
    parser.add_argument("--budget", type=float, default=0.02, help="USD limit per cell")
    parser.add_argument("task", nargs="?", default="What is (17 * 23) + 4? Use the tools, then answer in one line.")
    args = parser.parse_args()

    for model in args.model or ["openrouter"]:
        for agent_type in AGENT_TYPES:
            h = Harness(model, agent_type=agent_type, budget=args.budget, console=False)
            label = f"{agent_type.__name__} × {model}"
            try:
                answer = h.run(args.task)
            except Exception as e:  # one broken cell shouldn't hide the rest of the grid
                print(f"{label}: failed: {type(e).__name__}: {e}\n")
                continue
            print(f"{label}: {answer.strip()}\n  {h.report()}\n")


if __name__ == "__main__":
    main()
