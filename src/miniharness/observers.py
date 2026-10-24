"""Ready-made event subscribers."""

import dataclasses
import json
import sys
import time
from enum import Enum
from pathlib import Path
from typing import Any, TextIO

from miniharness.events import (
    Event,
    MessageRouted,
    ModelCalled,
    RunFinished,
    RunStarted,
    StateChanged,
    TokenStreamed,
    ToolCalled,
)


class ConsolePrinter:
    """Prints what the agent is doing, as it happens. Sub-agents are indented.

    Streamed tokens are printed inline as they arrive; the next other event
    starts a new line.
    """

    def __init__(self, stream: TextIO | None = None):
        self.stream = stream or sys.stdout
        self._mid_line = False  # inside a run of streamed tokens

    def __call__(self, event: Event) -> None:
        indent = "  " * event.depth
        if isinstance(event, TokenStreamed):
            if not self._mid_line:
                self.stream.write(f"  {indent}> ")
                self._mid_line = True
            self.stream.write(event.text.replace("\n", f"\n  {indent}  "))
            self.stream.flush()
            return
        if self._mid_line:
            self.stream.write("\n")
            self._mid_line = False
        match event:
            case RunStarted(task=task, agent=agent, depth=depth) if depth > 0:
                self._print(f"{indent}{agent} started: {_shorten(task)}")
            case StateChanged(new=new):
                self._print(f"{indent}[{new}]")
            case ModelCalled(stop_reason=stop, tool_calls=n, usage=usage, duration_s=secs):
                what = f"{n} tool call(s)" if n else stop
                self._print(f"{indent}model: {what}{_usage(usage)}, {secs:.1f}s")
            case ToolCalled(call=call, output=output, decision=decision):
                line = f"{call.name}({call.arguments}) -> {_shorten(output)}"
                if decision is not None and decision.verdict.value != "allow":
                    line += f"  (by {decision.policy})"
                self._print(indent + line)
            case MessageRouted(sender=sender, to=to, text=text):
                self._print(f"{indent}── {sender} → {to}: {_shorten(text, 100)}")
            case RunFinished():
                pass  # the caller prints the answer

    def _print(self, text: str) -> None:
        print(f"  {text}", file=self.stream)


class JsonlTracer:
    """Appends one JSON object per event to a file.

    Streamed tokens are skipped unless `tokens=True`: one line per token is mostly
    noise, and the full text is in the conversation anyway.
    """

    def __init__(self, path: Path | str, tokens: bool = False):
        self.path = Path(path)
        self.tokens = tokens
        self.started = time.monotonic()

    def __call__(self, event: Event) -> None:
        if isinstance(event, TokenStreamed) and not self.tokens:
            return
        record = {
            "event": type(event).__name__,
            "t": round(time.monotonic() - self.started, 3),
            **dataclasses.asdict(event),
        }
        # Opened per event: slower, but every line is on disk even if the run crashes
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=_json_default) + "\n")


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return repr(value)


def _usage(usage) -> str:
    if usage is None:
        return ""
    cost = "" if usage.cost_usd is None else f", ${usage.cost_usd:.6f}"
    return f", {usage.input_tokens} in / {usage.output_tokens} out{cost}"


def _shorten(text: str, limit: int = 80) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"
