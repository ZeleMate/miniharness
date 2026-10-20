from miniharness.types import LLMResponse, Message, ToolSpec


class MockProvider:
    """Replays scripted responses and records every conversation it was sent."""

    model = "mock"

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self.calls: list[list[Message]] = []

    def complete(self, messages: list[Message], tools: dict[str, ToolSpec]) -> LLMResponse:
        self.calls.append(list(messages))
        if not self._responses:
            raise RuntimeError("MockProvider ran out of scripted responses")
        return self._responses.pop(0)
