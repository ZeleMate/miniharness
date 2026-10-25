"""The agent loop.

Stage 1 (Template Method): `run()` is the fixed skeleton of the loop.
The steps it calls (`initial_messages`, `think`, `act`, `finish`) are the
hooks a subclass can override without touching the loop itself.

Stage 2 (Strategy): which LLM answers is a `Provider` passed in from outside.
The agent never knows which one it is talking to.

Stage 5 (Command): tool calls run through an injected `Toolbox`, which wraps
each one in a command object and keeps a history that can be undone.

Stage 9 (State): the loop is a state machine (see lifecycle.py). `step()`
advances one transition; `run()` is `start()` plus stepping until done.

Stage 10 (Observer): every transition goes through `start()`/`step()`, so
that's where RunStarted, StateChanged and RunFinished are emitted.

Stage 11 (Memento + Prototype): `checkpoint()` / `restore()` snapshot and
rewind the agent (and its file changes); `fork()` copies it to try a variant.

Stage 15 (Iterator): with `stream=True` the model's text arrives as
TokenStreamed events. `iter_run()` is the pull-based twin of the EventBus:
the same events, but the caller asks for each one with a `for` loop.

Bonus stage (Bridge): `Agent` is the abstraction, `Provider` the implementor.
Agent *types* (agent_types.py) are refined abstractions: they reshape the
loop with the `first_state()` and `after_answer()` hooks and reach the model
only through the provider, so any agent type runs on any provider.

Bonus stage (Singleton → dependency injection): every collaborator is passed
in, and the one the agent builds itself, the default Toolbox, it also wires to
its own event bus.

Bonus stage (concurrent tools): `act()` hands the Toolbox a whole turn's calls,
so it can run the read-only ones together (`Toolbox(max_workers=...)`).
"""

import copy
import warnings
from typing import Any, Callable, Iterator

from miniharness.checkpoint import Checkpoint
from miniharness.events import (
    Event,
    EventBus,
    RunFinished,
    RunStarted,
    StateChanged,
    agent_scope,
)
from miniharness.lifecycle import AgentState, Done, Idle, Thinking, from_snapshot
from miniharness.prompts import default_prompt
from miniharness.providers import Provider, stream_from
from miniharness.tools import Toolbox, ToolSet, default_tools, execute_all
from miniharness.types import LLMResponse, Message, StreamChunk, ToolCall


class Agent:
    def __init__(
        self,
        provider: Provider,
        system_prompt: str | None = None,
        tools: ToolSet | None = None,
        max_steps: int = 10,
        events: EventBus | None = None,
        name: str = "agent",
        stream: bool = False,
    ):
        self.name = name  # tags this agent's events; sub-agents use their tool name
        self.provider = provider
        self.events = events if events is not None else EventBus()
        # Whoever builds an object wires it (D98): the default Toolbox is ours, so it
        # reports to our bus; an injected one is wired by whoever built it (D76)
        self.tools = (
            tools if tools is not None else Toolbox(default_tools(), events=self.events)
        )
        self.system_prompt = (
            system_prompt if system_prompt is not None else default_prompt().build()
        )
        self.max_steps = max_steps
        self.stream = (
            stream  # think via provider.stream(), emitting TokenStreamed events
        )
        self.messages: list[Message] = []
        self.state: AgentState = Idle()
        self.model_calls = 0

    # --- lifecycle -----------------------------------------------------------

    def start(self, task: str) -> AgentState:
        if not isinstance(self.state, Idle) and not self.state.terminal:
            raise RuntimeError(f"Agent is already running ({self.state.name})")
        with agent_scope(self.name):
            self.messages = self.initial_messages(task)
            self.model_calls = 0
            self.events.emit(RunStarted(task))
            self._transition(self.first_state())
        return self.state

    def follow_up(self, text: str) -> AgentState:
        """Continue a finished run with a new user message (keeps the conversation)."""
        if not isinstance(self.state, Done):
            raise RuntimeError(
                f"Can only follow up on a finished run, not one that is {self.state.name}"
            )
        with agent_scope(self.name):
            self.messages.append(Message(role="user", content=text))
            self.model_calls = 0  # max_steps applies per turn
            self.events.emit(RunStarted(text))
            self._transition(Thinking())
        return self.state

    def step(self) -> AgentState:
        for _ in self._iter_step():
            pass
        return self.state

    def _iter_step(self) -> Iterator[None]:
        """One step as a generator that pauses whenever the state has news (a token).

        The agent scope is entered around each resume, never held across a `yield`:
        a ContextVar set in a generator stays set in the *caller* while it's paused,
        so the caller's own code would be tagged as this agent (DECISIONS.md D164).
        """
        work = self.state.iter_step(self)
        try:
            while True:
                with agent_scope(self.name):
                    try:
                        next(work)
                    except StopIteration as stop:
                        self._transition(stop.value)
                        if self.state.terminal:
                            self.events.emit(
                                RunFinished(self.state.name, self.state.answer)
                            )
                        return
                yield
        finally:
            work.close()  # abandoned mid-step: closes the provider's stream right away

    # --- iterator --------------------------------------------------------------

    def iter_run(self, task: str) -> Iterator[Event]:
        """`run()` as an iterator of events: `for event in agent.iter_run(task): ...`

        Yields every event the bus delivers during the run (including sub-agents'),
        in order, as soon as the agent pauses. Stopping early (`break`) leaves the
        agent at the start of the step it was in, so `step()` can carry on later.
        """
        return self._iter_events(lambda: self.start(task))

    def iter_continue(self) -> Iterator[Event]:
        """Like `iter_run`, from the current state (after `follow_up()` or `restore()`)."""
        return self._iter_events(None)

    def _iter_events(self, begin: Callable[[], Any] | None) -> Iterator[Event]:
        # Push -> pull: a subscriber buffers what the bus pushes, and the buffer is
        # emptied every time the agent pauses. Same events, same order as observers see.
        buffer: list[Event] = []
        unsubscribe = self.events.subscribe(buffer.append)
        try:
            if begin is not None:
                begin()
                yield from _flush(buffer)
            while not self.done:
                for _ in self._iter_step():
                    yield from _flush(buffer)
                yield from _flush(buffer)
        finally:
            unsubscribe()

    # --- memento -------------------------------------------------------------

    def checkpoint(self) -> Checkpoint:
        mark = self.tools.mark() if hasattr(self.tools, "mark") else None
        return Checkpoint.capture(
            self.messages, self.state.snapshot(), self.model_calls, mark
        )

    def restore(self, checkpoint: Checkpoint, files: bool = True) -> None:
        """Put the agent back where the checkpoint was taken.

        With `files=True`, file changes made since then are undone first. If
        they can't be (an irreversible action), nothing is restored at all.
        """
        if files:
            self._rewind_files(checkpoint)
        self.messages = list(copy.deepcopy(checkpoint.messages))
        self.model_calls = checkpoint.model_calls
        with agent_scope(self.name):
            self._transition(from_snapshot(checkpoint.state))

    def _rewind_files(self, checkpoint: Checkpoint) -> None:
        mark = checkpoint.tool_mark
        if mark is None:
            return
        if (
            not hasattr(self.tools, "rewind_to")
            or getattr(self.tools, "id", None) != mark.toolbox_id
        ):
            warnings.warn(
                "Checkpoint comes from another Toolbox (e.g. loaded from disk); file changes were not rewound",
                stacklevel=3,
            )
            return
        self.tools.rewind_to(mark)

    # --- prototype ------------------------------------------------------------

    def fork(self, checkpoint: Checkpoint | None = None, **overrides: Any) -> "Agent":
        """A copy of this agent that continues independently from `checkpoint`.

        The conversation is copied. Anything not overridden (provider, tools,
        events, ...) is shared with the original, so pass `tools=` to give the
        fork its own workspace and undo history.
        """
        checkpoint = checkpoint if checkpoint is not None else self.checkpoint()
        unknown = set(overrides) - {
            "provider",
            "tools",
            "system_prompt",
            "max_steps",
            "events",
            "name",
            "stream",
        }
        if unknown:
            raise TypeError(f"Can't override {sorted(unknown)}")
        clone = copy.copy(self)  # same class: a fork of a subclass is that subclass
        for name, value in overrides.items():
            setattr(clone, name, value)
        if clone.tools is self.tools and hasattr(self.tools, "history"):
            warnings.warn(
                "Fork shares the original's Toolbox: same workspace and undo history",
                stacklevel=2,
            )
        clone.restore(checkpoint, files=False)  # never rewind the original's files
        return clone

    def _transition(self, new: AgentState) -> None:
        old, self.state = self.state, new
        self.events.emit(StateChanged(old.name, new.name))

    @property
    def done(self) -> bool:
        return self.state.terminal

    # --- the template method -------------------------------------------------

    def run(self, task: str) -> str:
        self.start(task)
        while not self.done:
            self.step()
        return self.state.answer

    # --- hooks ---------------------------------------------------------------

    def first_state(self) -> AgentState:
        """Where `start()` enters the loop. A planner plans first (Planning)."""
        return Thinking()

    def initial_messages(self, task: str) -> list[Message]:
        return [
            Message(role="system", content=self.system_prompt),
            Message(role="user", content=task),
        ]

    def think(self, messages: list[Message]) -> LLMResponse:
        return self.provider.complete(messages, self.tools.specs())

    def think_stream(self, messages: list[Message]) -> Iterator[StreamChunk]:
        """Used instead of `think()` when `stream=True`. Override both to change thinking."""
        return stream_from(self.provider, messages, self.tools.specs())

    def act(self, tool_calls: list[ToolCall]) -> list[Message]:
        # The whole turn at once, so a Toolbox can run read-only calls together
        outputs = execute_all(self.tools, tool_calls)
        return [
            Message(role="tool", content=output, tool_call_id=tc.id)
            for tc, output in zip(
                tool_calls, outputs, strict=True
            )  # one output per call
        ]

    def after_answer(self, response: LLMResponse) -> AgentState:
        """What follows a reply without tool calls: Done, or another round (a review)."""
        return Done(self.finish(response))

    def finish(self, response: LLMResponse) -> str:
        if response.stop_reason not in ("end", "tool_calls"):
            return f"[stopped: {response.stop_reason}] {response.message.content}"
        return response.message.content


def _flush(buffer: list[Event]) -> Iterator[Event]:
    while buffer:
        yield buffer.pop(0)
