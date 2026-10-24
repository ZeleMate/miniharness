from miniharness.providers.registry import register_provider
from miniharness.types import LLMResponse, Message, ToolSpec


@register_provider("mock")
class MockProvider:
    """Replays scripted responses and records every conversation it was sent.

    A scripted item that is an exception gets raised instead of returned.
    """

    def __init__(self, responses: list[LLMResponse | Exception] | None = None, model: str = "mock"):
        self.model = model
        self._responses = list(responses or [])
        self.calls: list[list[Message]] = []

    def complete(self, messages: list[Message], tools: dict[str, ToolSpec]) -> LLMResponse:
        self.calls.append(list(messages))
        if not self._responses:
            raise RuntimeError("MockProvider ran out of scripted responses")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
