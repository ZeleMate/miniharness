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
"""

from miniharness.events import EventBus, RunFinished, RunStarted, StateChanged
from miniharness.lifecycle import AgentState, Idle, Thinking
from miniharness.prompts import default_prompt
from miniharness.providers import Provider
from miniharness.tools import Toolbox, ToolSet, default_tools
from miniharness.types import LLMResponse, Message, ToolCall


class Agent:
    def __init__(
        self,
        provider: Provider,
        system_prompt: str | None = None,
        tools: ToolSet | None = None,
        max_steps: int = 10,
        events: EventBus | None = None,
    ):
        self.provider = provider
        self.tools = tools if tools is not None else Toolbox(default_tools())
        self.system_prompt = system_prompt if system_prompt is not None else default_prompt().build()
        self.max_steps = max_steps
        self.events = events if events is not None else EventBus()
        self.messages: list[Message] = []
        self.state: AgentState = Idle()
        self.model_calls = 0

    # --- lifecycle -----------------------------------------------------------

    def start(self, task: str) -> AgentState:
        if not isinstance(self.state, Idle) and not self.state.terminal:
            raise RuntimeError(f"Agent is already running ({self.state.name})")
        self.messages = self.initial_messages(task)
        self.model_calls = 0
        self.events.emit(RunStarted(task))
        self._transition(Thinking())
        return self.state

    def step(self) -> AgentState:
        self._transition(self.state.step(self))
        if self.state.terminal:
            self.events.emit(RunFinished(self.state.name, self.state.answer))
        return self.state

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

    def initial_messages(self, task: str) -> list[Message]:
        return [
            Message(role="system", content=self.system_prompt),
            Message(role="user", content=task),
        ]

    def think(self, messages: list[Message]) -> LLMResponse:
        return self.provider.complete(messages, self.tools.specs())

    def act(self, tool_calls: list[ToolCall]) -> list[Message]:
        return [
            Message(role="tool", content=self.tools.execute(tc), tool_call_id=tc.id)
            for tc in tool_calls
        ]

    def finish(self, response: LLMResponse) -> str:
        if response.stop_reason not in ("end", "tool_calls"):
            return f"[stopped: {response.stop_reason}] {response.message.content}"
        return response.message.content
