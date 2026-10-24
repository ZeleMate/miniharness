"""Run the agent against a real model, through the Harness facade.

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
    uv run examples/hello.py --stream "Explain undo in two sentences"   # tokens as they arrive

Until stage 16 this file wired the provider stack, toolbox, policy, bus,
prompt, checkpoints and sub-agent by hand. Now it only maps flags to
`Harness` arguments; the wiring lives in miniharness/harness.py.
"""

import argparse

from dotenv import load_dotenv

from miniharness import Harness
from miniharness.providers import available_providers
from miniharness.tools import MaxCalls
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
    parser.add_argument("--stream", action="store_true", help="print the model's text as it arrives")
    parser.add_argument("--read-only", action="store_true", help="hide tools that change anything")
    parser.add_argument("--yes", action="store_true", help="approve every tool call that asks")
    parser.add_argument("--rewind", action="store_true", help="undo all file changes after the run")
    parser.add_argument("task", nargs="?", default="What is (17 * 23) + 4? Also, what time is it in UTC?")
    args = parser.parse_args()

    h = Harness(
        args.model,
        budget=args.budget,
        cache=args.cache,
        fallback=args.fallback,
        workspace="workspace",
        approve=True if args.yes else terminal_approver,
        policies=[MaxCalls("write_file", 5)],
        read_only=args.read_only,
        instructions=["Answer in plain text. No LaTeX or markdown math."],
        trace=args.trace,
        checkpoint=args.checkpoint,
        stream=args.stream,
    )
    if args.delegate:
        h.add_helper("researcher", "Reads files in the workspace and summarizes them.",
                     ["Read files to answer. Reply with a short summary."])
    print(f"[{type(h.stack.base).__name__} / {h.provider.model}]")

    if (saved := h.saved_run) is not None:
        print(f"  resuming from {args.checkpoint} ({saved.model_calls} model call(s) already made)")
        answer = h.resume()
    else:
        answer = h.run(args.task)  # the console printer shows progress live
    if not (args.stream and h.agent.state.name == "done"):  # a streamed answer was already shown
        print(f"\n{answer}")
    print(f"\n{h.report()}")

    if h.changes:
        print(f"\n{len(h.changes)} change(s) in ./{h.workspace}/")
        if args.rewind:
            for command in h.rewind():
                print(f"  undid {command.tool.name}({command.call.arguments.get('path')})")


if __name__ == "__main__":
    main()
