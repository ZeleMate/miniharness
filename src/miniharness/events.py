"""Observer: components announce what happened; subscribers decide what to do.

The Agent and Toolbox emit typed events on an EventBus. They never know who
is listening (a console printer, a trace file, a test) or whether anyone is.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Union

from miniharness.types import ToolCall, Usage

if TYPE_CHECKING:
    # Annotation only: importing it for real would create an import cycle
    # (events -> tools -> toolbox -> events)
    from miniharness.tools.policy import Decision


@dataclass(frozen=True)
class RunStarted:
    task: str


@dataclass(frozen=True)
class StateChanged:
    old: str
    new: str


@dataclass(frozen=True)
class ModelCalled:
    model: str
    stop_reason: str
    tool_calls: int
    usage: Usage | None
    duration_s: float


@dataclass(frozen=True)
class ToolCalled:
    call: ToolCall
    output: str
    decision: Decision | None  # None: the tool doesn't exist, so no policy ran
    failed: bool = False  # the tool ran and raised


@dataclass(frozen=True)
class RunFinished:
    state: str  # "done" or "stopped"
    answer: str


Event = Union[RunStarted, StateChanged, ModelCalled, ToolCalled, RunFinished]
Handler = Callable[[Event], None]


class EventBus:
    """Delivers each event to every subscriber, in subscription order.

    A failing subscriber is isolated: its error is recorded and warned about,
    and the remaining subscribers (and the run) carry on.
    """

    def __init__(self) -> None:
        self._handlers: list[Handler] = []
        self.errors: list[tuple[Handler, Event, Exception]] = []

    def subscribe(self, handler: Handler) -> Callable[[], None]:
        """Add a handler; returns a function that removes it again."""
        self._handlers.append(handler)
        return lambda: self._handlers.remove(handler)

    def emit(self, event: Event) -> None:
        for handler in list(self._handlers):  # a handler may unsubscribe itself
            try:
                handler(event)
            except Exception as e:
                self.errors.append((handler, event, e))
                warnings.warn(f"Event handler {handler!r} failed on {type(event).__name__}: {e!r}", stacklevel=2)
