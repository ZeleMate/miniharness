import pytest

from miniharness import Agent, LLMResponse, Message, ToolCall
from miniharness.providers import MockProvider
from miniharness.tools import run_tool


def test_answers_without_tools():
    provider = MockProvider([LLMResponse(Message(role="assistant", content="Hi!"), stop_reason="end")])

    assert Agent(provider).run("Say hi") == "Hi!"


def test_runs_tool_then_answers():
    provider = MockProvider([
        LLMResponse(
            Message(
                role="assistant",
                tool_calls=[ToolCall(id="call_1", name="multiply", arguments={"a": 17, "b": 23})],
            ),
            stop_reason="tool_calls",
        ),
        LLMResponse(Message(role="assistant", content="17 * 23 = 391"), stop_reason="end"),
    ])
    agent = Agent(provider)

    assert agent.run("What is 17 * 23?") == "17 * 23 = 391"
    tool_message = agent.messages[3]
    assert tool_message.role == "tool"
    assert tool_message.tool_call_id == "call_1"
    assert tool_message.content == "391"
    # The second model call saw the tool result
    assert provider.calls[1][-1] is tool_message


def test_stops_after_max_steps():
    looping = LLMResponse(
        Message(role="assistant", tool_calls=[ToolCall(id="c", name="current_time", arguments={})]),
        stop_reason="tool_calls",
    )
    with pytest.raises(RuntimeError, match="2 steps"):
        Agent(MockProvider([looping, looping]), max_steps=2).run("loop forever")


def test_tool_errors_are_returned_as_text():
    assert run_tool("nope", {}).startswith("Error: unknown tool")
    assert run_tool("add", {"a": 1}).startswith("Error: TypeError")
