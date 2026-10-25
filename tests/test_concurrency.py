"""Concurrent tool calls: consecutive read-only calls run together (DECISIONS.md D215-D223)."""

import threading
import time

import pytest

from miniharness import Agent, Harness, LLMResponse, Message, ToolCall
from miniharness.events import EventBus, ToolCalled, agent_scope, current_depth
from miniharness.providers import MockProvider
from miniharness.team import Team
from miniharness.tools import (
    AgentTool,
    MaxCalls,
    PolicyChain,
    Tool,
    Toolbox,
    ToolboxView,
    ToolResult,
    Verdict,
)


def call(name, id=None, **arguments):
    return ToolCall(id=id or f"id-{name}", name=name, arguments=arguments)


class Meet(Tool):
    """Read-only: waits until `parties` calls are inside at once. Proves they overlap."""

    name = "meet"
    description = "Wait for the others."

    def __init__(self, parties: int, timeout: float = 2):
        self.barrier = threading.Barrier(parties, timeout=timeout)

    def run(self, label: str = "") -> ToolResult:
        self.barrier.wait()  # BrokenBarrierError (an error result) if run one at a time
        return ToolResult(f"met {label}")


class Probe(Tool):
    """Records when each call starts and ends, and how many ran at once."""

    name = "probe"
    description = "Record a visit."

    def __init__(self, name: str = "probe", side_effects: bool = False, thread_safe: bool = True):
        self.name = name
        self.side_effects = side_effects
        self.thread_safe = thread_safe
        self.log: list[tuple[str, str]] = []
        self.threads: list[threading.Thread] = []
        self.active = 0
        self.most_active = 0
        self._lock = threading.Lock()

    def run(self, label: str = "", fail: bool = False) -> ToolResult:
        with self._lock:
            self.log.append(("start", label))
            self.threads.append(threading.current_thread())
            self.active += 1
            self.most_active = max(self.most_active, self.active)
        time.sleep(0.02)
        with self._lock:
            self.active -= 1
            self.log.append(("end", label))
        if fail:
            raise ValueError(f"{label} failed")
        return ToolResult(label)


def box(*tools, workers=4, **kwargs):
    kwargs.setdefault("policy", PolicyChain.allow_all())
    return Toolbox(list(tools), max_workers=workers, **kwargs)


# --- Which calls run together --------------------------------------------------


def test_consecutive_read_only_calls_run_at_the_same_time():
    tools = box(Meet(3))

    outputs = tools.execute_all([call("meet", label=x) for x in "abc"])

    assert outputs == ["met a", "met b", "met c"]


def test_by_default_calls_run_one_at_a_time_on_the_callers_thread():
    probe = Probe()
    tools = Toolbox([probe], policy=PolicyChain.allow_all())  # max_workers=1

    tools.execute_all([call("probe", label="a"), call("probe", label="b")])

    assert probe.most_active == 1
    assert probe.threads == [threading.current_thread()] * 2


def test_by_default_each_call_is_reported_before_the_next_one_runs():
    events = EventBus()
    probe = Probe()
    events.subscribe(lambda event: probe.log.append(("event", event.call.arguments["label"])))
    tools = Toolbox([probe], policy=PolicyChain.allow_all(), events=events)

    tools.execute_all([call("probe", label="a"), call("probe", label="b")])

    assert probe.log == [
        ("start", "a"), ("end", "a"), ("event", "a"),
        ("start", "b"), ("end", "b"), ("event", "b"),
    ]


def test_a_call_with_side_effects_runs_alone_between_the_reads():
    read, write = Probe("read"), Probe("write", side_effects=True)
    log = read.log = write.log = []  # one shared timeline
    tools = box(read, write)

    tools.execute_all(
        [call("read", label="r1"), call("read", label="r2"), call("write", label="w"), call("read", label="r3")]
    )

    assert log.index(("start", "w")) > max(log.index(("end", "r1")), log.index(("end", "r2")))
    assert log.index(("start", "r3")) > log.index(("end", "w"))
    assert read.most_active == 2  # r1 and r2 did overlap


def test_a_tool_that_isnt_thread_safe_runs_alone():
    probe = Probe(thread_safe=False)
    tools = box(probe)

    tools.execute_all([call("probe", label=x) for x in "abc"])

    assert probe.most_active == 1


def test_sub_agents_are_not_run_in_parallel():
    helper = AgentTool("helper", "A helper.", Agent(MockProvider(), tools=Toolbox([])))

    assert helper.side_effects is False  # read-only, and still kept out of parallel groups
    assert helper.thread_safe is False


def test_a_group_never_uses_more_threads_than_max_workers():
    probe = Probe()
    tools = box(probe, workers=2)

    tools.execute_all([call("probe", label=x) for x in "abcde"])

    assert probe.most_active == 2


def test_max_workers_must_be_positive():
    with pytest.raises(ValueError, match="max_workers"):
        Toolbox([], max_workers=0)


# --- Order: outputs, history and events follow the model, not the threads ---------


class Slow(Tool):
    """`first` waits until `second` has finished, so they finish in reverse order."""

    description = "Finish in reverse order."

    def __init__(self, name: str, wait_for: threading.Event | None, done: threading.Event):
        self.name = name
        self.wait_for = wait_for
        self.done = done

    def run(self) -> ToolResult:
        if self.wait_for is not None:
            assert self.wait_for.wait(timeout=2), "the other call never ran"
        self.done.set()
        return ToolResult(self.name)


def test_outputs_history_and_events_keep_the_models_order():
    second_done, first_done = threading.Event(), threading.Event()
    events = EventBus()
    seen = []
    events.subscribe(seen.append)
    tools = box(Slow("first", second_done, first_done), Slow("second", None, second_done), events=events)

    outputs = tools.execute_all([call("first"), call("second")])

    assert outputs == ["first", "second"]
    assert [c.call.name for c in tools.history] == ["first", "second"]
    assert [e.call.name for e in seen if isinstance(e, ToolCalled)] == ["first", "second"]


def test_events_are_emitted_on_the_callers_thread():
    threads = []
    events = EventBus()
    events.subscribe(lambda event: threads.append(threading.current_thread()))
    tools = box(Meet(2), events=events)

    tools.execute_all([call("meet"), call("meet")])

    assert threads == [threading.current_thread()] * 2


# --- Policies, errors and context ------------------------------------------------


def test_policies_decide_in_order_on_the_callers_thread():
    seen = []

    class Recording:
        def check(self, call, tool):
            seen.append((call.id, threading.current_thread()))
            return None

    policy = PolicyChain([Recording(), MaxCalls("probe", 2)], default=Verdict.ALLOW)
    tools = box(Probe(), policy=policy)

    outputs = tools.execute_all([call("probe", id=x, label=x) for x in "abc"])

    assert seen == [(x, threading.current_thread()) for x in "abc"]
    assert outputs[:2] == ["a", "b"]
    assert outputs[2].startswith("Permission denied")  # the third call, in the model's order
    assert [c.id for c, _ in tools.denied] == ["c"]


def test_a_failing_call_doesnt_disturb_the_rest_of_its_group():
    tools = box(Probe())

    outputs = tools.execute_all(
        [call("probe", label="a"), call("probe", label="b", fail=True), call("nope"), call("probe", label="c")]
    )

    assert outputs[0] == "a" and outputs[3] == "c"
    assert outputs[1] == "Error: ValueError: b failed"
    assert outputs[2] == "Error: unknown tool 'nope'"
    assert [c.result.output for c in tools.history] == ["a", "c"]


def test_workers_see_the_agent_that_is_running():
    class Depth(Tool):
        name = "depth"
        description = "Report the current agent depth."
        barrier = threading.Barrier(2, timeout=2)

        def run(self) -> ToolResult:
            self.barrier.wait()  # both calls overlap, so they really ran in workers
            return ToolResult(str(current_depth()))

    tools = box(Depth())

    with agent_scope("parent"):
        outputs = tools.execute_all([call("depth"), call("depth")])

    assert outputs == ["0", "0"]  # without a copied context it would be -1


def test_execute_is_a_batch_of_one():
    tools = box(Probe())

    assert tools.execute(call("probe", label="a")) == "a"
    assert len(tools.history) == 1


# --- Proxies pass the batches on (D221) -------------------------------------------------


def test_a_view_keeps_the_calls_it_allows_running_together():
    tools = box(Meet(2), Probe("secret"))
    view = ToolboxView(tools, allow=["meet"])

    outputs = view.execute_all([call("meet", label="a"), call("meet", label="b"), call("secret")])

    assert outputs == ["met a", "met b", "Error: unknown tool 'secret'"]
    assert tools.tools["secret"].log == []


def test_team_members_keep_their_tools_running_together():
    member = Agent(MockProvider(), tools=box(Meet(2)))
    reviewer = Agent(MockProvider(), tools=Toolbox([]))
    team = Team({"writer": member, "reviewer": reviewer}, {"writer": ["reviewer"]}, finishers={"reviewer"})

    outputs = team.members["writer"].tools.execute_all(
        [call("meet", label="a"), call("meet", label="b"), call("send_message", to="reviewer", text="hi")]
    )

    assert outputs == ["met a", "met b", "Message sent to reviewer."]


# --- Agent and Harness -------------------------------------------------------------


def two_meetings_then(answer):
    calls = [call("meet", id="1", label="a"), call("meet", id="2", label="b")]
    return [
        LLMResponse(Message(role="assistant", tool_calls=calls), "tool_calls"),
        LLMResponse(Message(role="assistant", content=answer), "end"),
    ]


def test_the_agent_runs_one_turns_calls_together():
    agent = Agent(MockProvider(two_meetings_then("done")), tools=box(Meet(2)))

    assert agent.run("meet twice") == "done"
    replies = [(m.tool_call_id, m.content) for m in agent.messages if m.role == "tool"]
    assert replies == [("1", "met a"), ("2", "met b")]


def test_an_agent_still_accepts_a_tool_set_without_execute_all():
    class OneByOne:
        def specs(self):
            return {}

        def execute(self, call):
            return f"ran {call.name}"

    agent = Agent(MockProvider(two_meetings_then("done")), tools=OneByOne())

    assert agent.run("meet twice") == "done"
    assert [m.content for m in agent.messages if m.role == "tool"] == ["ran meet", "ran meet"]


@pytest.mark.parametrize("read_only", [False, True])
def test_harness_tool_workers_turn_it_on(read_only):
    h = Harness(
        MockProvider(two_meetings_then("done")), tools=[Meet(2)], tool_workers=2, read_only=read_only, budget=None, console=False
    )

    assert h.run("meet twice") == "done"
    assert h.toolbox.max_workers == 2
