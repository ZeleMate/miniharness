import os
from typing import Any

from miniharness.adapters.openai_chat import OpenAIChatAdapter
from miniharness.types import LLMResponse, Message, ToolSpec

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider:
    def __init__(self, model: str | None = None, client: Any = None):
        self.model = model or os.environ.get("OPENROUTER_MODEL", "deepseek/deepseek-chat")
        if client is None:
            from openai import OpenAI

            client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=os.environ["OPENROUTER_API_KEY"])
        self.client = client
        self.adapter = OpenAIChatAdapter()

    def complete(self, messages: list[Message], tools: dict[str, ToolSpec]) -> LLMResponse:
        request = self.adapter.to_wire(messages, tools)
        response = self.client.chat.completions.create(model=self.model, **request)
        return self.adapter.from_wire(response)
