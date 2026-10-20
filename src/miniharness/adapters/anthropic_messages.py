"""Adapter: our types <-> the Anthropic Messages wire format.

Pure translation, no network. Differences from the OpenAI format: the system
prompt is a separate parameter, tool calls are `tool_use` content blocks, and
tool results go inside a *user* message.
"""

from typing import Any

from miniharness.types import LLMResponse, Message, ToolCall, ToolSpec

_STOP_REASONS = {"tool_use": "tool_calls", "end_turn": "end"}


class AnthropicMessagesAdapter:
    def to_wire(self, messages: list[Message], tools: dict[str, ToolSpec]) -> dict[str, Any]:
        wire: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "user":
                wire.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                wire.append({"role": "assistant", "content": self._assistant_content(m)})
            elif m.role == "tool":
                block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
                # All results for one assistant turn must share a single user message
                last = wire[-1] if wire else None
                if last and last["role"] == "user" and isinstance(last["content"], list):
                    last["content"].append(block)
                else:
                    wire.append({"role": "user", "content": [block]})

        request: dict[str, Any] = {"messages": wire}
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        if system:
            request["system"] = system
        if tools:
            request["tools"] = [
                {"name": name, "description": spec["description"], "input_schema": spec["parameters"]}
                for name, spec in tools.items()
            ]
        return request

    def from_wire(self, response: Any) -> LLMResponse:
        text = "".join(b.text for b in response.content if b.type == "text")
        tool_calls = [
            ToolCall(id=b.id, name=b.name, arguments=b.input)
            for b in response.content
            if b.type == "tool_use"
        ]
        return LLMResponse(
            message=Message(role="assistant", content=text, tool_calls=tool_calls, raw=response.content),
            stop_reason=_STOP_REASONS.get(response.stop_reason, response.stop_reason),
        )

    def _assistant_content(self, m: Message) -> Any:
        if m.raw is not None:
            # Replay Anthropic's own content unchanged (keeps thinking blocks valid)
            return m.raw
        content: list[dict[str, Any]] = []
        if m.content:
            content.append({"type": "text", "text": m.content})
        for tc in m.tool_calls:
            content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
        return content
