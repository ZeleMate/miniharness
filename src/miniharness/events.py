"""Observer: components announce what happened; subscribers decide what to do.

The Agent and Toolbox emit typed events on an EventBus. They never know who
is listening (a console printer, a trace file, a test) or whether anyone is.
"""

from __future__ import annotations

import warnings
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Callable, Iterator, Union

from miniharness.types import ToolCall, Usage

if TYPE_CHECKING:
    # Annotation only: importing it for real would create an import cycle
    # (events -> tools -> toolbox -> events)
    from miniharness.tools.policy import Decision


# Every event also carries `agent` and `depth`, filled in by the bus from the
# agent that is running when the event is emitted (see agent_scope below).


@dataclass(frozen=True)
class RunStarted:
    task: str
    agent: str = ""
    depth: int = 0


@dataclass(frozen=True)
class StateChanged:
    old: str
    new: str
    agent: str = ""
    depth: int = 0


@dataclass(frozen=True)
class ModelCalled:
    model: str
    stop_reason: str
    tool_calls: int
    usage: Usage | None
    duration_s: float
    agent: str = ""
    depth: int = 0


@dataclass(frozen=True)
class TokenStreamed:
    """A piece of model text, as it arrives. Only emitted when the agent streams."""

    text: str
    agent: str = ""
    depth: int = 0


@dataclass(frozen=True)
class ToolCalled:
    call: ToolCall
    output: str
    decision: Decision | None  # None: the tool doesn't exist, so no policy ran
    failed: bool = False  # the tool ran and raised
    agent: str = ""
    depth: int = 0


@dataclass(frozen=True)
class MessageRouted:
    """A team mediator delivered a message from one member to another."""

    sender: str
    to: str
    text: str
    agent: str = ""
    depth: int = 0


@dataclass(frozen=True)
class RunFinished:
    state: str  # "done" or "stopped"
    answer: str
    agent: str = ""
    depth: int = 0


Event = Union[
    RunStarted,
    StateChanged,
    TokenStreamed,
    ModelCalled,
    ToolCalled,
    MessageRouted,
    RunFinished,
]
Handler = Callable[[Event], None]


# --- Which agent is running? ---------------------------------------------------
# A ContextVar instead of passing (agent, depth) through every call: a sub-agent
# runs *inside* its parent's tool call, so the innermost scope is always the
# agent doing the work. ContextVars are also safe with threads and asyncio.

_scope: ContextVar[tuple[str, int] | None] = ContextVar("agent_scope", default=None)


@contextmanager
def agent_scope(name: str) -> Iterator[int]:
    """Mark `name` as the running agent; nested scopes are one level deeper."""
    parent = _scope.get()
    depth = 0 if parent is None else parent[1] + 1
    token = _scope.set((name, depth))
    try:
        yield depth
    finally:
        _scope.reset(token)


def current_depth() -> int:
    """Depth of the running agent, or -1 outside any agent."""
    scope = _scope.get()
    return -1 if scope is None else scope[1]


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
        scope = _scope.get()
        if scope is not None:
            event = replace(event, agent=scope[0], depth=scope[1])
        for handler in list(self._handlers):  # a handler may unsubscribe itself
            try:
                handler(event)
            except Exception as e:
                self.errors.append((handler, event, e))
                warnings.warn(
                    f"Event handler {handler!r} failed on {type(event).__name__}: {e!r}",
                    stacklevel=2,
                )
