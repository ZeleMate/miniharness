"""State: the agent's lifecycle, one class per state.

    Idle --start()--> Thinking --tool calls--> ActingOnTools --> Thinking ...
                         |
                         +--answer--> Done        (terminal)
                         +--StopRun-> Stopped     (terminal)

Each state's `step()` does that state's work and returns the next state.
The states call the agent's Template Method hooks (think, act, finish), so
subclasses that override a hook keep working.
"""

from typing import TYPE_CHECKING

from miniharness.errors import StopRun
from miniharness.types import ToolCall

if TYPE_CHECKING:
    from miniharness.agent import Agent


class AgentState:
    name: str
    terminal = False

    def step(self, agent: "Agent") -> "AgentState":
        raise RuntimeError(f"Cannot step an agent that is {self.name}")

    def __repr__(self) -> str:
        return f"<{self.name}>"


class Idle(AgentState):
    name = "idle"


class Thinking(AgentState):
    name = "thinking"

    def step(self, agent):
        if agent.model_calls >= agent.max_steps:
            raise RuntimeError(f"Agent did not finish within {agent.max_steps} steps")
        agent.model_calls += 1
        try:
            response = agent.think(agent.messages)
        except StopRun as e:
            return Stopped(e.reason, str(e))
        agent.messages.append(response.message)
        if response.stop_reason == "tool_calls":
            return ActingOnTools(response.message.tool_calls)
        return Done(agent.finish(response))


class ActingOnTools(AgentState):
    name = "acting_on_tools"

    def __init__(self, calls: list[ToolCall]):
        self.calls = calls

    def step(self, agent):
        agent.messages.extend(agent.act(self.calls))
        return Thinking()


class Done(AgentState):
    name = "done"
    terminal = True

    def __init__(self, answer: str):
        self.answer = answer


class Stopped(AgentState):
    name = "stopped"
    terminal = True

    def __init__(self, reason: str, detail: str):
        self.reason = reason
        self.detail = detail

    @property
    def answer(self) -> str:
        return f"[stopped: {self.reason}] {self.detail}"
