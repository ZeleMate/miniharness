"""The agent loop.

Stage 1 (Template Method): `run()` is the fixed skeleton of the loop.
The steps it calls (`initial_messages`, `think`, `act`, `finish`) are the
hooks a subclass can override without touching the loop itself.

Stage 2 (Strategy): which LLM answers is a `Provider` passed in from outside.
The agent never knows which one it is talking to.
"""

from miniharness.prompts import default_prompt
from miniharness.providers import Provider
from miniharness.tools import TOOLS, run_tool
from miniharness.types import LLMResponse, Message, ToolCall

class Agent:
    def __init__(
        self,
        provider: Provider,
        system_prompt: str | None = None,
        max_steps: int = 10,
    ):
        self.provider = provider
        self.system_prompt = system_prompt if system_prompt is not None else default_prompt().build()
        self.max_steps = max_steps
        self.messages: list[Message] = []

    # --- the template method -------------------------------------------------

    def run(self, task: str) -> str:
        self.messages = self.initial_messages(task)
        for _ in range(self.max_steps):
            response = self.think(self.messages)
            self.messages.append(response.message)
            if response.stop_reason != "tool_calls":
                return self.finish(response)
            self.messages.extend(self.act(response.message.tool_calls))
        raise RuntimeError(f"Agent did not finish within {self.max_steps} steps")

    # --- hooks ---------------------------------------------------------------

    def initial_messages(self, task: str) -> list[Message]:
        return [
            Message(role="system", content=self.system_prompt),
            Message(role="user", content=task),
        ]

    def think(self, messages: list[Message]) -> LLMResponse:
        return self.provider.complete(messages, TOOLS)

    def act(self, tool_calls: list[ToolCall]) -> list[Message]:
        return [
            Message(role="tool", content=run_tool(tc.name, tc.arguments), tool_call_id=tc.id)
            for tc in tool_calls
        ]

    def finish(self, response: LLMResponse) -> str:
        if response.stop_reason not in ("end", "tool_calls"):
            return f"[stopped: {response.stop_reason}] {response.message.content}"
        return response.message.content
