"""Pull the agent's run with a for loop instead of subscribing to it.

    uv run examples/stream.py                                  # OpenRouter, default model
    uv run examples/stream.py "Name three uses of undo"
    uv run examples/stream.py --max-words 15 "Tell me a long story"   # stop early

No observers are subscribed: everything printed comes from iterating
`agent.iter_run()`. Breaking out of the loop stops the model mid-answer and
closes the HTTP stream (the provider's `finally` runs when the generator closes).
"""

import argparse
from contextlib import closing

from dotenv import load_dotenv

from miniharness import Agent
from miniharness.events import (
    EventBus,
    ModelCalled,
    RunFinished,
    TokenStreamed,
    ToolCalled,
)
from miniharness.providers import UsageTracker, create_provider
from miniharness.tools import Toolbox, default_tools


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--model", default="openrouter", help="provider[:model]")
    parser.add_argument(
        "--max-words", type=int, help="stop after this many streamed words"
    )
    parser.add_argument(
        "task",
        nargs="?",
        default="What is 17 * 23? Then explain in two sentences how you got it.",
    )
    args = parser.parse_args()

    tracker = UsageTracker(create_provider(args.model))
    events = (
        EventBus()
    )  # shared, so ToolCalled reaches the iterator too (D98); nobody subscribes
    agent = Agent(
        tracker,
        tools=Toolbox(default_tools(), events=events),
        events=events,
        stream=True,
    )
    print(f"[{tracker.model}]\n")

    words = 0
    # closing(): stop deterministically on break, not when the generator is garbage-collected
    with closing(agent.iter_run(args.task)) as run:
        for event in run:
            match event:
                case TokenStreamed(text=text):
                    print(text, end="", flush=True)
                    words += len(text.split())
                    if args.max_words and words >= args.max_words:
                        print(" […stopped by the caller]")
                        break
                case ToolCalled(call=call, output=output):
                    print(f"\n  ⚙ {call.name}({call.arguments}) -> {output}\n")
                case ModelCalled(usage=usage, duration_s=secs) if usage is not None:
                    print(f"\n  ({usage.output_tokens} tokens, {secs:.1f}s)")
                case RunFinished(state=state):
                    print(f"\n[{state}]")

    total = tracker.total
    cost = "unknown" if total.cost_usd is None else f"${total.cost_usd:.6f}"
    print(f"\nagent is {agent.state.name}; {len(tracker.calls)} model call(s), {cost}")


if __name__ == "__main__":
    main()
