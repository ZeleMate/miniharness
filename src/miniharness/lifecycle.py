"""State: the agent's lifecycle, one class per state.

    Idle --start()--> Thinking --tool calls--> ActingOnTools --> Thinking ...
           |             |
           |             +--answer--> agent.after_answer(): Done (terminal), or Thinking again
           |             +--StopRun-> Stopped     (terminal)
           +--(PlannerAgent)--> Planning --plan--> Thinking ...

`start()` enters `agent.first_state()`: Thinking, or Planning for a PlannerAgent.

Each state's `step()` does that state's work and returns the next state.
The states call the agent's Template Method hooks (think, act, finish), so
subclasses that override a hook keep working.

Stage 15 (Iterator): `iter_step()` is the same work as a generator. It yields
whenever there is news mid-step (a streamed token), so the agent can hand
control back to whoever is iterating, and *returns* the next state. Only
the model-calling states have news mid-step; the default just runs `step()`.

Bonus stage (Bridge): every state that calls the model goes through one
`model_call()` helper, so a new agent type's extra calls (Planning, a review
round) stream, count toward `max_steps` and emit ModelCalled like the main loop.
"""

import time
from typing import TYPE_CHECKING, Any, Generator, Iterator

from miniharness.errors import StopRun
from miniharness.events import ModelCalled, TokenStreamed
from miniharness.providers import stream_from
from miniharness.types import Completed, LLMResponse, Message, StreamChunk, TextDelta, ToolCall, ToolSpec

if TYPE_CHECKING:
    from miniharness.agent import Agent


class AgentState:
    name: str
    terminal = False

    def step(self, agent: "Agent") -> "AgentState":
        raise RuntimeError(f"Cannot step an agent that is {self.name}")

    def iter_step(self, agent: "Agent") -> "StepGenerator":
        return self.step(agent)
        yield  # unreachable, but makes this a generator

    def snapshot(self) -> dict[str, Any]:
        """JSON-safe data needed to rebuild this state (see from_snapshot)."""
        return {"name": self.name}

    def __repr__(self) -> str:
        return f"<{self.name}>"


class Idle(AgentState):
    name = "idle"


class Thinking(AgentState):
    name = "thinking"

    def step(self, agent):
        return drain(self.iter_step(agent))

    def iter_step(self, agent):
        try:
            response = yield from model_call(agent, agent.messages)
        except StopRun as e:
            return Stopped(e.reason, str(e))
        agent.messages.append(response.message)
        if response.stop_reason == "tool_calls":
            return ActingOnTools(response.message.tool_calls)
        return agent.after_answer(response)  # Done, unless the agent type wants another round


class Planning(AgentState):
    """PlannerAgent's first state: one call for a plan, with no tools, then the normal loop.

    The request for a plan is shown to the model but not kept. The conversation
    gets the plan and a "carry it out" message, so roles still alternate
    (system, user, assistant, user) for every provider.
    """

    name = "planning"

    def step(self, agent):
        return drain(self.iter_step(agent))

    def iter_step(self, agent):
        ask = Message(role="user", content=agent.plan_request())
        try:
            response = yield from model_call(agent, [*agent.messages, ask], tools={})
        except StopRun as e:
            return Stopped(e.reason, str(e))
        # A fresh message: tool calls (if a provider made any anyway) and the raw
        # payload are dropped, so no unanswered tool call is replayed later
        plan = response.message.content.strip() or "(no plan)"
        agent.messages.append(Message(role="assistant", content=plan))
        agent.messages.append(Message(role="user", content=agent.execute_request))
        return Thinking()


def model_call(
    agent: "Agent", messages: list[Message], tools: dict[str, ToolSpec] | None = None
) -> Generator[None, None, LLMResponse]:
    """One model call, with the bookkeeping every model-calling state shares.

    Counts toward `max_steps`, streams when the agent streams (pausing at each
    token), and emits ModelCalled. `tools=None` goes through the agent's
    `think` / `think_stream` hooks, as the main loop does. A dict asks the
    provider directly with exactly those tools (a side call, such as planning).
    StopRun is left to the caller.
    """
    if agent.model_calls >= agent.max_steps:
        raise RuntimeError(f"Agent did not finish within {agent.max_steps} steps")
    agent.model_calls += 1
    started = time.monotonic()
    if agent.stream:
        chunks = agent.think_stream(messages) if tools is None else stream_from(agent.provider, messages, tools)
        response = yield from _consume_stream(agent, chunks)
    else:
        response = agent.think(messages) if tools is None else agent.provider.complete(messages, tools)
    agent.events.emit(
        ModelCalled(
            model=agent.provider.model,
            stop_reason=response.stop_reason,
            tool_calls=len(response.message.tool_calls),
            usage=response.usage,
            duration_s=time.monotonic() - started,
        )
    )
    return response


def _consume_stream(agent: "Agent", chunks: Iterator[StreamChunk]) -> Generator[None, None, LLMResponse]:
    response = None
    try:
        for chunk in chunks:  # to the end, not just to Completed (see collect())
            if isinstance(chunk, TextDelta):
                agent.events.emit(TokenStreamed(chunk.text))
                yield
            elif isinstance(chunk, Completed):
                response = chunk.response
    finally:
        # If the consumer stops early, close the provider's stream (and its HTTP
        # connection) now, not whenever the garbage collector gets to it
        close = getattr(chunks, "close", None)
        if close is not None:
            close()
    if response is None:
        raise RuntimeError("Stream ended without a Completed chunk")
    return response


class ActingOnTools(AgentState):
    name = "acting_on_tools"

    def __init__(self, calls: list[ToolCall]):
        self.calls = calls

    def snapshot(self):
        return {"name": self.name, "calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in self.calls]}

    def step(self, agent):
        agent.messages.extend(agent.act(self.calls))
        return Thinking()


class Done(AgentState):
    name = "done"
    terminal = True

    def __init__(self, answer: str):
        self.answer = answer

    def snapshot(self):
        return {"name": self.name, "answer": self.answer}


class Stopped(AgentState):
    name = "stopped"
    terminal = True

    def __init__(self, reason: str, detail: str):
        self.reason = reason
        self.detail = detail

    def snapshot(self):
        return {"name": self.name, "reason": self.reason, "detail": self.detail}

    @property
    def answer(self) -> str:
        return f"[stopped: {self.reason}] {self.detail}"


StepGenerator = Generator[None, None, AgentState]


def drain(steps: StepGenerator) -> AgentState:
    """Run a step generator to the end and return the state it returns."""
    while True:
        try:
            next(steps)
        except StopIteration as stop:
            return stop.value


def from_snapshot(data: dict[str, Any]) -> AgentState:
    name = data["name"]
    if name == "idle":
        return Idle()
    if name == "thinking":
        return Thinking()
    if name == "planning":
        return Planning()
    if name == "acting_on_tools":
        return ActingOnTools([ToolCall(**c) for c in data["calls"]])
    if name == "done":
        return Done(data["answer"])
    if name == "stopped":
        return Stopped(data["reason"], data["detail"])
    raise ValueError(f"Unknown agent state {name!r}")
