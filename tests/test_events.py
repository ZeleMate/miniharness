import io
import json

import pytest

from miniharness import Agent, LLMResponse, Message, ToolCall
from miniharness.errors import BudgetExceeded
from miniharness.events import (
    EventBus,
    ModelCalled,
    RunFinished,
    RunStarted,
    StateChanged,
    ToolCalled,
)
from miniharness.observers import ConsolePrinter, JsonlTracer
from miniharness.providers import MockProvider
from miniharness.tools import (
    PolicyChain,
    Toolbox,
    WriteFile,
    default_policy,
    default_tools,
)
from miniharness.types import Usage


def tool_turn(name="add", **arguments):
    return LLMResponse(
        Message(
            role="assistant",
            tool_calls=[
                ToolCall(id="c", name=name, arguments=arguments or {"a": 1, "b": 2})
            ],
        ),
        "tool_calls",
        Usage(10, 2, 0.001),
    )


def answer(text="3"):
    return LLMResponse(
        Message(role="assistant", content=text), "end", Usage(12, 1, 0.001)
    )


def recorded_run(script, toolbox=None):
    bus = EventBus()
    events = []
    bus.subscribe(events.append)
    if toolbox is None:
        toolbox = Toolbox(default_tools(), events=bus)
    else:
        toolbox.events = bus
    Agent(MockProvider(script), tools=toolbox, events=bus).run("1+2?")
    return events


# --- The bus -----------------------------------------------------------------------


def test_handlers_receive_events_in_subscription_order():
    bus, seen = EventBus(), []
    bus.subscribe(lambda e: seen.append(("a", e)))
    bus.subscribe(lambda e: seen.append(("b", e)))

    bus.emit(RunStarted("x"))

    assert [who for who, _ in seen] == ["a", "b"]


def test_unsubscribe():
    bus, seen = EventBus(), []
    unsubscribe = bus.subscribe(seen.append)
    unsubscribe()

    bus.emit(RunStarted("x"))

    assert seen == []


def test_a_failing_handler_is_isolated_recorded_and_warned():
    bus, seen = EventBus(), []

    def broken(event):
        raise OSError("disk full")

    bus.subscribe(broken)
    bus.subscribe(seen.append)

    with pytest.warns(UserWarning, match="disk full"):
        bus.emit(RunStarted("x"))

    assert len(seen) == 1  # the next handler still ran
    assert isinstance(bus.errors[0][2], OSError)


def test_a_broken_observer_does_not_stop_the_run():
    bus = EventBus()
    bus.subscribe(lambda e: 1 / 0)

    with pytest.warns(UserWarning):
        result = Agent(MockProvider([answer("fine")]), events=bus).run("x")

    assert result == "fine"


# --- What the Agent and Toolbox emit ---------------------------------------------------


def test_a_run_tells_the_whole_story_in_order():
    events = recorded_run([tool_turn(), answer("3")])

    assert [type(e) for e in events] == [
        RunStarted,
        StateChanged,  # idle -> thinking
        ModelCalled,
        StateChanged,  # thinking -> acting_on_tools
        ToolCalled,
        StateChanged,  # acting_on_tools -> thinking
        ModelCalled,
        StateChanged,  # thinking -> done
        RunFinished,
    ]
    states = [(e.old, e.new) for e in events if isinstance(e, StateChanged)]
    assert states[0] == ("idle", "thinking") and states[-1] == ("thinking", "done")
    assert (events[-1].state, events[-1].answer) == ("done", "3")


def test_model_called_carries_usage_and_tool_count():
    events = recorded_run([tool_turn(), answer()])

    first = next(e for e in events if isinstance(e, ModelCalled))
    assert first.tool_calls == 1 and first.stop_reason == "tool_calls"
    assert first.usage == Usage(10, 2, 0.001)
    assert first.duration_s >= 0


def test_tool_called_carries_the_policy_decision(tmp_path):
    toolbox = Toolbox(
        [WriteFile(tmp_path)], policy=default_policy(approver=lambda c: False)
    )

    events = recorded_run(
        [tool_turn("write_file", path="a.txt", content="x"), answer()], toolbox
    )

    [called] = [e for e in events if isinstance(e, ToolCalled)]
    assert called.decision.verdict.value == "deny"
    assert called.decision.policy == "AskBeforeSideEffects"
    assert called.output.startswith("Permission denied")


def test_unknown_and_failing_tools_are_reported():
    bus, events = EventBus(), []
    bus.subscribe(events.append)
    toolbox = Toolbox(default_tools(), policy=PolicyChain.allow_all(), events=bus)

    toolbox.execute(ToolCall(id="1", name="nope", arguments={}))
    toolbox.execute(ToolCall(id="2", name="add", arguments={"a": 1}))

    unknown, failed = events
    assert unknown.decision is None
    assert failed.failed and failed.output.startswith("Error: TypeError")


def test_a_stopped_run_finishes_with_the_stopped_state():
    events = recorded_run([BudgetExceeded("over")])

    assert (events[-1].state, events[-1].answer) == (
        "stopped",
        "[stopped: budget] over",
    )
    assert not any(isinstance(e, ModelCalled) for e in events)  # no call was made


def test_overriding_think_keeps_model_events():
    class Custom(Agent):
        def think(self, messages):
            return super().think(messages)

    bus, events = EventBus(), []
    bus.subscribe(events.append)
    Custom(MockProvider([answer()]), events=bus).run("x")

    assert any(isinstance(e, ModelCalled) for e in events)


# --- Observers -----------------------------------------------------------------------------


def test_console_printer_shows_progress():
    out = io.StringIO()
    printer = ConsolePrinter(out)

    for event in recorded_run([tool_turn(), answer()]):
        printer(event)

    text = out.getvalue()
    assert "[thinking]" in text and "[done]" in text
    assert "add({'a': 1, 'b': 2}) -> 3" in text
    assert "model: 1 tool call(s), 10 in / 2 out, $0.001000" in text


def test_console_printer_names_the_denying_policy(tmp_path):
    out = io.StringIO()
    toolbox = Toolbox([WriteFile(tmp_path)], policy=default_policy(approver=None))

    for event in recorded_run(
        [tool_turn("write_file", path="a.txt", content="x"), answer()], toolbox
    ):
        ConsolePrinter(out)(event)

    assert "(by AskBeforeSideEffects)" in out.getvalue()


def test_jsonl_tracer_writes_one_parseable_line_per_event(tmp_path):
    path = tmp_path / "trace.jsonl"
    tracer = JsonlTracer(path)
    events = recorded_run([tool_turn(), answer()])

    for event in events:
        tracer(event)

    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(lines) == len(events)
    assert lines[0]["event"] == "RunStarted" and lines[0]["task"] == "1+2?"
    tool = next(line for line in lines if line["event"] == "ToolCalled")
    assert tool["call"]["name"] == "add" and tool["decision"]["verdict"] == "allow"


# --- D98: whoever builds an object wires it (Singleton → DI) ------------------------------


def test_the_default_toolbox_reports_to_the_agents_bus():
    agent = Agent(MockProvider([tool_turn(), answer()]))
    events = []
    agent.events.subscribe(events.append)

    agent.run("1+2?")

    assert [type(e) for e in events if isinstance(e, ToolCalled)] == [ToolCalled]
    assert agent.tools.events is agent.events


def test_an_injected_toolbox_is_left_as_its_builder_wired_it():
    toolbox = Toolbox(
        default_tools()
    )  # no bus: the caller's choice, not the agent's to fix (D76)
    agent = Agent(MockProvider([answer()]), tools=toolbox)

    assert toolbox.events is None and agent.events is not None
