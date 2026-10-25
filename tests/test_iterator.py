"""The agent as an iterator: streamed tokens, `iter_run()`, and pull vs push."""

import io
import json

from miniharness import Agent, LLMResponse, Message, ToolCall
from miniharness.errors import BudgetExceeded
from miniharness.events import (
    EventBus,
    ModelCalled,
    RunFinished,
    RunStarted,
    StateChanged,
    TokenStreamed,
    ToolCalled,
    current_depth,
)
from miniharness.observers import ConsolePrinter, JsonlTracer
from miniharness.providers import MockProvider
from miniharness.tools import Add, AgentTool, Toolbox
from miniharness.types import Completed, TextDelta


def call(name, **arguments):
    return LLMResponse(
        Message(
            role="assistant",
            tool_calls=[ToolCall(id=f"c-{name}", name=name, arguments=arguments)],
        ),
        "tool_calls",
    )


def answer(text):
    return LLMResponse(Message(role="assistant", content=text), "end")


def make_agent(script, stream=True, **kwargs):
    events = kwargs.pop("events", None) or EventBus()
    tools = kwargs.pop("tools", None) or Toolbox([Add()], events=events)
    return Agent(
        MockProvider(script), tools=tools, events=events, stream=stream, **kwargs
    )


def kinds(events):
    return [type(e).__name__ for e in events]


# --- Streaming through the bus (push) ---------------------------------------------------


def test_a_streaming_agent_emits_tokens_before_the_model_call_event():
    agent = make_agent([answer("Hello there world")])
    seen = []
    agent.events.subscribe(seen.append)

    assert agent.run("hi") == "Hello there world"

    tokens = [e.text for e in seen if isinstance(e, TokenStreamed)]
    assert tokens == ["Hello ", "there ", "world"]
    assert kinds(seen).index("TokenStreamed") < kinds(seen).index("ModelCalled")
    assert all(e.agent == "agent" for e in seen)


def test_a_non_streaming_agent_emits_no_tokens():
    agent = make_agent([answer("Hello")], stream=False)
    seen = []
    agent.events.subscribe(seen.append)

    agent.run("hi")

    assert not any(isinstance(e, TokenStreamed) for e in seen)


def test_the_conversation_is_the_same_streamed_or_not():
    script = [call("add", a=2, b=3), answer("It is 5.")]
    streamed, plain = make_agent(list(script)), make_agent(list(script), stream=False)

    assert streamed.run("2+3?") == plain.run("2+3?")
    assert [(m.role, m.content) for m in streamed.messages] == [
        (m.role, m.content) for m in plain.messages
    ]


def test_a_budget_stop_while_streaming_ends_the_run_cleanly():
    class Broke:
        model = "broke"

        def complete(self, messages, tools):
            raise AssertionError("not used when streaming")

        def stream(self, messages, tools):
            raise BudgetExceeded("no money")
            yield

    agent = Agent(Broke(), tools=Toolbox([Add()]), stream=True)

    assert agent.run("hi") == "[stopped: budget] no money"


def test_overriding_think_stream_changes_streamed_thinking():
    class Canned(Agent):
        def think_stream(self, messages):
            yield TextDelta("canned")
            yield Completed(answer("canned"))

    agent = Canned(MockProvider([]), tools=Toolbox([]), stream=True)

    assert agent.run("hi") == "canned"


# --- iter_run (pull) ----------------------------------------------------------------


def test_iter_run_yields_exactly_what_the_bus_pushes():
    agent = make_agent([call("add", a=2, b=3), answer("It is 5.")])
    pushed = []
    agent.events.subscribe(pushed.append)

    pulled = list(agent.iter_run("2+3?"))

    assert pulled == pushed
    assert kinds(pulled) == [
        "RunStarted", "StateChanged",                       # idle -> thinking
        "ModelCalled", "StateChanged",                      # -> acting_on_tools
        "ToolCalled", "StateChanged",                       # -> thinking
        "TokenStreamed", "TokenStreamed", "TokenStreamed",  # "It ", "is ", "5."
        "ModelCalled", "StateChanged", "RunFinished",       # -> done
    ]  # fmt: skip
    assert agent.state.answer == "It is 5."


def test_iter_run_hands_control_back_at_every_token():
    agent = make_agent([answer("a b c")])
    progress = []

    for event in agent.iter_run("hi"):
        if isinstance(event, TokenStreamed):
            progress.append((event.text, len(agent.messages)))

    # The answer isn't in the conversation yet while its tokens are arriving: we're mid-step
    assert progress == [("a ", 2), ("b ", 2), ("c", 2)]
    assert len(agent.messages) == 3


def test_iter_run_is_lazy():
    agent = make_agent([answer("hi")])

    events = agent.iter_run("task")

    assert (
        agent.state.name == "idle"
    )  # nothing happens until the first event is asked for
    next(events)
    assert agent.state.name == "thinking"


def test_breaking_out_mid_stream_closes_the_stream_and_leaves_the_agent_resumable():
    provider = MockProvider([answer("one two three four"), answer("again")])
    agent = Agent(provider, tools=Toolbox([]), stream=True)
    pushed = []
    agent.events.subscribe(pushed.append)

    for event in agent.iter_run("count"):
        if isinstance(event, TokenStreamed) and event.text.strip() == "two":
            break

    assert (
        agent.state.name == "thinking"
    )  # the step never finished, so nothing was recorded
    assert len(agent.messages) == 2
    assert len(agent.events._handlers) == 1  # iter_run's buffer unsubscribed itself

    assert agent.step().name == "done"  # carry on: thinks again from the same point
    assert agent.state.answer == "again"


def test_the_callers_code_between_events_is_not_tagged_as_the_agent():
    agent = make_agent([answer("x y")])
    depths = []

    for _ in agent.iter_run("hi"):
        depths.append(current_depth())

    assert set(depths) == {-1}  # the agent scope is never held across a yield


def test_iter_run_includes_sub_agent_events_at_their_depth():
    bus = EventBus()
    sub = Agent(
        MockProvider([answer("five")]), tools=Toolbox([]), events=bus, stream=True
    )
    helper = AgentTool("helper", "Adds numbers.", sub)
    parent = make_agent(
        [call("helper", task="2+3?"), answer("The helper says five.")],
        events=bus,
        tools=Toolbox([helper], events=bus),
    )

    events = list(parent.iter_run("ask"))

    sub_tokens = [
        e for e in events if isinstance(e, TokenStreamed) and e.agent == "helper"
    ]
    assert [e.text for e in sub_tokens] == ["five"]
    assert sub_tokens[0].depth == 1
    # The sub-run comes before the tool call that started it (post-order, as on the bus)
    tool = next(i for i, e in enumerate(events) if isinstance(e, ToolCalled))
    assert events.index(sub_tokens[0]) < tool


def test_iter_continue_drives_a_follow_up():
    agent = make_agent([answer("first"), answer("second")])
    list(agent.iter_run("one"))

    agent.follow_up("two")
    events = list(agent.iter_continue())

    assert isinstance(events[-1], RunFinished)
    assert events[-1].answer == "second"
    assert not any(
        isinstance(e, RunStarted) for e in events
    )  # follow_up() emitted it already


def test_iter_run_works_without_streaming_one_step_at_a_time():
    agent = make_agent([call("add", a=1, b=1), answer("2")], stream=False)

    events = list(agent.iter_run("1+1"))

    assert not any(isinstance(e, TokenStreamed) for e in events)
    assert [e.new for e in events if isinstance(e, StateChanged)] == [
        "thinking",
        "acting_on_tools",
        "thinking",
        "done",
    ]


def test_a_fork_can_turn_streaming_on():
    agent = make_agent([answer("plain")], stream=False)
    agent.run("hi")

    fork = agent.fork(
        stream=True, provider=MockProvider([answer("streamed now")]), tools=Toolbox([])
    )
    fork.follow_up("again")

    assert any(isinstance(e, TokenStreamed) for e in fork.iter_continue())


# --- Observers ---------------------------------------------------------------------


def test_console_prints_tokens_inline_then_starts_a_new_line():
    out = io.StringIO()
    agent = make_agent([answer("Hello world")])
    agent.events.subscribe(ConsolePrinter(out))

    agent.run("hi")

    lines = out.getvalue().splitlines()
    assert "  > Hello world" in lines
    assert lines[lines.index("  > Hello world") + 1].startswith("  model: end")


def test_tracer_skips_tokens_unless_asked(tmp_path):
    quiet, loud = tmp_path / "quiet.jsonl", tmp_path / "loud.jsonl"
    agent = make_agent([answer("a b")])
    agent.events.subscribe(JsonlTracer(quiet))
    agent.events.subscribe(JsonlTracer(loud, tokens=True))

    agent.run("hi")

    def names(path):
        return [json.loads(line)["event"] for line in path.read_text().splitlines()]

    assert "TokenStreamed" not in names(quiet)
    assert names(loud).count("TokenStreamed") == 2
    assert ModelCalled.__name__ in names(quiet)
