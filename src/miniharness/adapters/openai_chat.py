"""Adapter: our types <-> the OpenAI chat-completions wire format.

Pure translation, no network. Works for any OpenAI-compatible server
(OpenRouter, Ollama, vLLM, ...).
"""

import json
from collections.abc import Iterable, Iterator
from typing import Any

from miniharness.errors import MalformedResponseError
from miniharness.types import (
    Completed,
    LLMResponse,
    Message,
    StreamChunk,
    TextDelta,
    ToolCall,
    ToolSpec,
    Usage,
)


class OpenAIChatAdapter:
    def to_wire(
        self, messages: list[Message], tools: dict[str, ToolSpec]
    ) -> dict[str, Any]:
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
        calls = [
            (tc.id, tc.function.name, tc.function.arguments)
            for tc in (choice.message.tool_calls or [])
        ]
        return self._response(
            choice.message.content or "",
            calls,
            choice.finish_reason,
            self._usage(response),
        )

    def from_stream(self, chunks: Iterable[Any]) -> Iterator[StreamChunk]:
        """Translate a `stream=True` response: text as it arrives, then the whole response.

        Tool calls arrive in fragments keyed by `index` (the id and name first, then
        pieces of the JSON arguments), so they are assembled here and only appear in
        the final Completed. Usage comes in a last chunk with no choices.
        """
        text: list[str] = []
        calls: dict[int, list[str]] = {}  # index -> [id, name, arguments so far]
        finish_reason = None
        usage = None
        for chunk in chunks:
            if getattr(chunk, "usage", None) is not None:
                usage = self._usage(chunk)
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if delta.content:
                text.append(delta.content)
                yield TextDelta(delta.content)
            for tc in delta.tool_calls or []:
                call = calls.setdefault(tc.index, ["", "", ""])
                call[0] = tc.id or call[0]
                if tc.function is not None:
                    call[1] = tc.function.name or call[1]
                    call[2] += tc.function.arguments or ""
            finish_reason = choice.finish_reason or finish_reason
        ordered = [tuple(calls[i]) for i in sorted(calls)]
        yield Completed(self._response("".join(text), ordered, finish_reason, usage))

    def _response(
        self,
        content: str,
        calls: list[tuple[str, str, str]],
        finish_reason: str | None,
        usage: Usage | None,
    ) -> LLMResponse:
        try:
            tool_calls = [
                ToolCall(id=id_, name=name, arguments=json.loads(arguments or "{}"))
                for id_, name, arguments in calls
            ]
        except json.JSONDecodeError as e:
            raise MalformedResponseError(
                f"Tool-call arguments are not valid JSON: {e}", usage
            ) from e
        if tool_calls:
            stop = "tool_calls"
        elif finish_reason == "length":
            stop = "max_tokens"
        elif finish_reason == "content_filter":
            stop = "refusal"  # so a FallbackChain can pass it on, like Anthropic's refusals
        else:
            stop = "end"
        return LLMResponse(
            message=Message(role="assistant", content=content, tool_calls=tool_calls),
            stop_reason=stop,
            usage=usage,
        )

    def _usage(self, response: Any) -> Usage | None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        # OpenRouter adds `cost` (USD); plain OpenAI-compatible servers don't
        return Usage(
            usage.prompt_tokens, usage.completion_tokens, getattr(usage, "cost", None)
        )

    def _message(self, m: Message) -> dict[str, Any]:
        if m.role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": m.content or None}
            if m.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in m.tool_calls
                ]
            return entry
        if m.role == "tool":
            return {
                "role": "tool",
                "tool_call_id": m.tool_call_id,
                "content": m.content,
            }
        return {"role": m.role, "content": m.content}
