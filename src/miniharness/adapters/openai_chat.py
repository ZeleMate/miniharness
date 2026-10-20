"""Adapter: our types <-> the OpenAI chat-completions wire format.

Pure translation, no network. Works for any OpenAI-compatible server
(OpenRouter, Ollama, vLLM, ...).
"""

import json
from typing import Any

from miniharness.types import LLMResponse, Message, ToolCall, ToolSpec


class OpenAIChatAdapter:
    def to_wire(self, messages: list[Message], tools: dict[str, ToolSpec]) -> dict[str, Any]:
        request: dict[str, Any] = {"messages": [self._message(m) for m in messages]}
        if tools:
            request["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": spec["description"],
                        "parameters": spec["parameters"],
                    },
                }
                for name, spec in tools.items()
            ]
        return request

    def from_wire(self, response: Any) -> LLMResponse:
        choice = response.choices[0]
        tool_calls = [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=json.loads(tc.function.arguments or "{}"),
            )
            for tc in (choice.message.tool_calls or [])
        ]
        if tool_calls:
            stop = "tool_calls"
        elif choice.finish_reason == "length":
            stop = "max_tokens"
        else:
            stop = "end"
        return LLMResponse(
            message=Message(
                role="assistant",
                content=choice.message.content or "",
                tool_calls=tool_calls,
            ),
            stop_reason=stop,
        )

    def _message(self, m: Message) -> dict[str, Any]:
        if m.role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": m.content or None}
            if m.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in m.tool_calls
                ]
            return entry
        if m.role == "tool":
            return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
        return {"role": m.role, "content": m.content}
