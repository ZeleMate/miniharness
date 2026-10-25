"""Characterization tests: pin down exactly what goes over the wire.

Fake SDK clients (injected into the providers) record the request and return canned responses, so these
run offline. They exist to keep refactors honest: the payloads must not change.
"""

from types import SimpleNamespace as NS

import pytest

from miniharness.providers import AnthropicProvider, OpenRouterProvider
from miniharness.tools import Toolbox, default_tools
from miniharness.types import Message, ToolCall

TOOLS = Toolbox(default_tools()).specs()

CONVERSATION = [
    Message(role="system", content="Be brief."),
    Message(role="user", content="What is 2*3 and the time?"),
    Message(
        role="assistant",
        content="Let me check.",
        tool_calls=[
            ToolCall(id="c1", name="multiply", arguments={"a": 2, "b": 3}),
            ToolCall(id="c2", name="current_time", arguments={}),
        ],
    ),
    Message(role="tool", content="6", tool_call_id="c1"),
    Message(role="tool", content="2026-01-01T00:00:00", tool_call_id="c2"),
]


class FakeClient:
    """Stands in for both SDK clients: records kwargs, returns a canned response."""

    def __init__(self, response):
        self.response = response
        self.requests: list[dict] = []
        self.chat = NS(completions=NS(create=self._create))  # OpenAI shape
        self.messages = NS(create=self._create)  # Anthropic shape

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.response


# --- OpenRouter (OpenAI chat format) -----------------------------------------


def openai_response(content=None, tool_calls=None, finish_reason="stop"):
    return NS(
        choices=[
            NS(
                message=NS(content=content, tool_calls=tool_calls),
                finish_reason=finish_reason,
            )
        ]
    )


def test_openrouter_request_payload():
    client = FakeClient(openai_response(content="done"))

    OpenRouterProvider("some/model", client).complete(CONVERSATION, TOOLS)

    req = client.requests[0]
    assert req["model"] == "some/model"
    assert req["messages"] == [
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "What is 2*3 and the time?"},
        {
            "role": "assistant",
            "content": "Let me check.",
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "multiply", "arguments": '{"a": 2, "b": 3}'}},
                {"id": "c2", "type": "function", "function": {"name": "current_time", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "6"},
        {"role": "tool", "tool_call_id": "c2", "content": "2026-01-01T00:00:00"},
    ]
    assert req["tools"][0] == {
        "type": "function",
        "function": {
            "name": "add",
            "description": TOOLS["add"]["description"],
            "parameters": TOOLS["add"]["parameters"],
        },
    }


def test_openrouter_parses_tool_calls():
    tc = NS(id="x1", function=NS(name="add", arguments='{"a": 1, "b": 2}'))
    client = FakeClient(openai_response(tool_calls=[tc], finish_reason="tool_calls"))

    resp = OpenRouterProvider("m", client).complete(CONVERSATION[:2], TOOLS)

    assert resp.stop_reason == "tool_calls"
    assert resp.message.content == ""
    assert resp.message.tool_calls == [ToolCall(id="x1", name="add", arguments={"a": 1, "b": 2})]


@pytest.mark.parametrize(("finish", "expected"), [("stop", "end"), ("length", "max_tokens"), ("content_filter", "refusal")])
def test_openrouter_stop_reasons(finish, expected):
    client = FakeClient(openai_response(content="hi", finish_reason=finish))

    assert OpenRouterProvider("m", client).complete(CONVERSATION[:2], TOOLS).stop_reason == expected


def test_openrouter_omits_tools_when_empty():
    client = FakeClient(openai_response(content="hi"))

    OpenRouterProvider("m", client).complete(CONVERSATION[:2], {})

    assert "tools" not in client.requests[0]


# --- Anthropic ---------------------------------------------------------------


def anthropic_response(blocks, stop_reason="end_turn"):
    return NS(content=blocks, stop_reason=stop_reason)


def test_anthropic_request_payload():
    client = FakeClient(anthropic_response([NS(type="text", text="done")]))

    AnthropicProvider("claude-x", client).complete(CONVERSATION, TOOLS)

    req = client.requests[0]
    assert req["model"] == "claude-x"
    assert req["max_tokens"] == 16000
    assert req["system"] == "Be brief."
    assert req["messages"] == [
        {"role": "user", "content": "What is 2*3 and the time?"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Let me check."},
                {"type": "tool_use", "id": "c1", "name": "multiply", "input": {"a": 2, "b": 3}},
                {"type": "tool_use", "id": "c2", "name": "current_time", "input": {}},
            ],
        },
        {
            "role": "user",
            "content": [  # both results share one user message
                {"type": "tool_result", "tool_use_id": "c1", "content": "6"},
                {"type": "tool_result", "tool_use_id": "c2", "content": "2026-01-01T00:00:00"},
            ],
        },
    ]
    assert req["tools"][0] == {
        "name": "add",
        "description": TOOLS["add"]["description"],
        "input_schema": TOOLS["add"]["parameters"],
    }


def test_anthropic_replays_raw_assistant_content():
    client = FakeClient(anthropic_response([NS(type="text", text="ok")]))
    raw = [NS(type="thinking", thinking=""), NS(type="text", text="earlier")]
    convo = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="earlier", raw=raw),
        Message(role="user", content="again"),
    ]

    AnthropicProvider("claude-x", client).complete(convo, {})

    assert client.requests[0]["messages"][1] == {"role": "assistant", "content": raw}
    assert "system" not in client.requests[0]
    assert "tools" not in client.requests[0]


def test_anthropic_parses_response():
    blocks = [
        NS(type="thinking", thinking=""),
        NS(type="text", text="Checking."),
        NS(type="tool_use", id="t1", name="add", input={"a": 1, "b": 2}),
    ]
    client = FakeClient(anthropic_response(blocks, stop_reason="tool_use"))

    resp = AnthropicProvider("claude-x", client).complete(CONVERSATION[:2], TOOLS)

    assert resp.stop_reason == "tool_calls"
    assert resp.message.content == "Checking."
    assert resp.message.tool_calls == [ToolCall(id="t1", name="add", arguments={"a": 1, "b": 2})]
    assert resp.message.raw is blocks


@pytest.mark.parametrize(
    ("stop", "expected"),
    [("end_turn", "end"), ("max_tokens", "max_tokens"), ("refusal", "refusal")],
)
def test_anthropic_stop_reasons(stop, expected):
    client = FakeClient(anthropic_response([NS(type="text", text="x")], stop_reason=stop))

    assert AnthropicProvider("claude-x", client).complete(CONVERSATION[:2], TOOLS).stop_reason == expected
