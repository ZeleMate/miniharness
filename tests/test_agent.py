import pytest

from miniharness import Agent, LLMResponse, Message, ToolCall
from miniharness.providers import MockProvider
from miniharness.tools import Toolbox, default_tools


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


def test_tool_calls_go_through_the_injected_toolbox():
    toolbox = Toolbox(default_tools())
    provider = MockProvider([
        LLMResponse(
            Message(role="assistant", tool_calls=[ToolCall(id="c", name="add", arguments={"a": 1, "b": 2})]),
            stop_reason="tool_calls",
        ),
        LLMResponse(Message(role="assistant", content="3"), stop_reason="end"),
    ])

    Agent(provider, tools=toolbox).run("1+2?")

    assert [c.call.name for c in toolbox.history] == ["add"]
