"""Run the agent against a real model.

    python examples/hello.py                      # OpenRouter (default)
    python examples/hello.py --provider anthropic
"""

import argparse

from dotenv import load_dotenv

from miniharness import Agent


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="openrouter", choices=["openrouter", "anthropic"])
    parser.add_argument("--model", default=None)
    parser.add_argument("task", nargs="?", default="What is (17 * 23) + 4? Also, what time is it in UTC?")
    args = parser.parse_args()

    agent = Agent(provider=args.provider, model=args.model)
    print(f"[{agent.provider} / {agent.model}]")
    answer = agent.run(args.task)

    for m in agent.messages[2:]:
        if m.role == "tool":
            print(f"  tool -> {m.content}")
        for tc in m.tool_calls:
            print(f"  call {tc.name}({tc.arguments})")
    print(f"\n{answer}")


if __name__ == "__main__":
    main()
