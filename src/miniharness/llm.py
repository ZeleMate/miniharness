"""Calling the LLM.

NAIVE ON PURPOSE. This is the "before" picture for your first refactor
(stage 2 -> Strategy + Adapter). Notice what hurts as you read it:

- one function branches on a provider string, so every new provider edits it
- SDK clients are rebuilt on every call
- message translation is buried inline, so you can't test it without a network
- the mock provider reads a module-level global (tests must mutate shared state)

Don't fix it yet. Feel it first, then write down what bugs you in PATTERNS.md.
"""

import json
import os
from typing import Any

from miniharness.types import LLMResponse, Message, ToolCall

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Scripted responses for provider="mock". Tests push onto this list.
MOCK_RESPONSES: list[LLMResponse] = []


def call_llm(
    provider: str,
    model: str,
    messages: list[Message],
    tools: dict[str, dict[str, Any]],
) -> LLMResponse:
    if provider == "mock":
        if not MOCK_RESPONSES:
            raise RuntimeError("MockLLM ran out of scripted responses")
        return MOCK_RESPONSES.pop(0)

    elif provider == "openrouter":
        from openai import OpenAI

        client = OpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=os.environ["OPENROUTER_API_KEY"],
        )

        # --- translate our messages -> OpenAI chat format ---
        oa_messages: list[dict[str, Any]] = []
        for m in messages:
            if m.role in ("system", "user"):
                oa_messages.append({"role": m.role, "content": m.content})
            elif m.role == "assistant":
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
                oa_messages.append(entry)
            elif m.role == "tool":
                oa_messages.append(
                    {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
                )

        kwargs: dict[str, Any] = {"model": model, "messages": oa_messages}
        if tools:
            kwargs["tools"] = [
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

        resp = client.chat.completions.create(**kwargs)

        # --- translate the response back ---
        choice = resp.choices[0]
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

    elif provider == "anthropic":
        import anthropic

        client = anthropic.Anthropic()

        # --- translate our messages -> Anthropic format ---
        # Differences from OpenAI: system is a separate parameter, tool calls
        # are content blocks, and tool results go inside a *user* message.
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        an_messages: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                continue
            elif m.role == "user":
                an_messages.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                if m.raw is not None:
                    # Replay Anthropic's own content unchanged (keeps thinking blocks valid)
                    content: Any = m.raw
                else:
                    content = []
                    if m.content:
                        content.append({"type": "text", "text": m.content})
                    for tc in m.tool_calls:
                        content.append(
                            {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
                        )
                an_messages.append({"role": "assistant", "content": content})
            elif m.role == "tool":
                block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
                # All results for one assistant turn must share a single user message
                last = an_messages[-1] if an_messages else None
                if last and last["role"] == "user" and isinstance(last["content"], list):
                    last["content"].append(block)
                else:
                    an_messages.append({"role": "user", "content": [block]})

        kwargs = {"model": model, "max_tokens": 16000, "messages": an_messages}
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [
                {"name": name, "description": spec["description"], "input_schema": spec["parameters"]}
                for name, spec in tools.items()
            ]

        resp = client.messages.create(**kwargs)

        # --- translate the response back ---
        text = "".join(b.text for b in resp.content if b.type == "text")
        tool_calls = [
            ToolCall(id=b.id, name=b.name, arguments=b.input)
            for b in resp.content
            if b.type == "tool_use"
        ]
        stop = {"tool_use": "tool_calls", "end_turn": "end"}.get(resp.stop_reason, resp.stop_reason)
        return LLMResponse(
            message=Message(role="assistant", content=text, tool_calls=tool_calls, raw=resp.content),
            stop_reason=stop,
        )

    else:
        raise ValueError(f"Unknown provider: {provider!r}")
