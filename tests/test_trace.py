import pytest

from miniharness import Agent, LLMResponse, Message, ToolCall
from miniharness.events import EventBus
from miniharness.observers import JsonlTracer
from miniharness.providers import MockProvider
from miniharness.team import Team
from miniharness.tools import Add, AgentTool, Tool, Toolbox, ToolResult, WriteFile, default_policy
from miniharness.trace import (
    CostSummary,
    HtmlReport,
    MessageNode,
    ModelCallNode,
    RunNode,
    ToolCallNode,
    TraceVisitor,
    load_trace,
)
from miniharness.types import Usage


def tool(name, cost=0.001, **arguments):
    return LLMResponse(
        Message(role="assistant", tool_calls=[ToolCall(id=f"c-{name}", name=name, arguments=arguments)]),
        "tool_calls",
        Usage(100, 10, cost),
    )


def say(text, cost=0.001):
    return LLMResponse(Message(role="assistant", content=text), "end", Usage(50, 5, cost))


@pytest.fixture
def traced(tmp_path):
    """A bus that records to a JSONL file; returns (bus, load)."""
    path = tmp_path / "trace.jsonl"
    bus = EventBus()
    bus.subscribe(JsonlTracer(path))
    return bus, lambda: load_trace(path)


def delegation_run(bus):
    helper = AgentTool(
        "helper",
        "Adds numbers.",
        Agent(MockProvider([tool("add", a=2, b=3), say("five", cost=0.002)]), tools=Toolbox([Add()], events=bus), events=bus),
    )
    parent = Agent(
        MockProvider([tool("helper", task="2+3?"), say("The helper says five.")]),
        tools=Toolbox([helper], events=bus),
        events=bus,
        name="main",
    )
    parent.run("Ask the helper.")


# --- Building the tree -------------------------------------------------------------------


def test_a_sub_agent_run_nests_under_the_tool_call_that_started_it(traced):
    bus, load = traced
    delegation_run(bus)

    trace = load()

    [root] = trace.children
    assert (root.agent, root.state, root.answer) == ("main", "done", "The helper says five.")
    model1, helper_call, model2 = root.children
    assert isinstance(model1, ModelCallNode) and isinstance(model2, ModelCallNode)
    assert isinstance(helper_call, ToolCallNode) and helper_call.name == "helper"
    [sub] = helper_call.children
    assert (sub.agent, sub.depth, sub.task, sub.answer) == ("helper", 1, "2+3?", "five")
    assert [type(c).__name__ for c in sub.children] == ["ModelCallNode", "ToolCallNode", "ModelCallNode"]


def test_team_messages_and_member_turns_are_top_level(traced):
    bus, load = traced
    writer = Agent(MockProvider([tool("send_message", to="reviewer", text="draft"), say("sent")]), tools=Toolbox([]), events=bus)
    reviewer = Agent(MockProvider([tool("approve"), say("ok")]), tools=Toolbox([]), events=bus)
    Team({"writer": writer, "reviewer": reviewer}, {"writer": ["reviewer"]}, {"reviewer"}).run("writer", "Write.")

    trace = load()

    kinds = [(type(c).__name__, getattr(c, "agent", None) or getattr(c, "to", None)) for c in trace.children]
    assert kinds == [("MessageNode", "writer"), ("RunNode", "writer"), ("MessageNode", "reviewer"), ("RunNode", "reviewer")]


def test_an_unfinished_trace_still_builds(traced):
    bus, load = traced
    agent = Agent(MockProvider([tool("add", a=1, b=1)]), events=bus)
    agent.start("1+1")
    agent.step()  # model asked for a tool; the run never finishes

    [run] = load().children
    assert run.state == "unfinished"


# --- Visitors ------------------------------------------------------------------------------


def test_cost_summary_breaks_costs_down_by_agent(traced):
    bus, load = traced
    delegation_run(bus)
    summary = CostSummary()

    load().accept(summary)

    main, helper = summary.by_agent["main"], summary.by_agent["helper"]
    assert (main.model_calls, main.tool_calls, main.cost_usd) == (2, 1, pytest.approx(0.002))
    assert (helper.model_calls, helper.tool_calls, helper.cost_usd) == (2, 1, pytest.approx(0.003))
    assert summary.total().cost_usd == pytest.approx(0.005)
    assert summary.total().input_tokens == 300


def test_cost_summary_counts_denials(traced, tmp_path):
    bus, load = traced
    box = Toolbox([WriteFile(tmp_path)], policy=default_policy(approver=None), events=bus)
    Agent(MockProvider([tool("write_file", path="a", content="x"), say("ok")]), tools=box, events=bus).run("w")
    summary = CostSummary()

    load().accept(summary)

    assert summary.total().denied == 1


def test_unknown_cost_makes_the_total_unknown(traced):
    bus, load = traced
    Agent(MockProvider([say("x", cost=None)]), events=bus).run("t")
    summary = CostSummary()

    load().accept(summary)

    assert summary.total().cost_usd is None
    assert "unknown" in summary.table()


def test_a_new_operation_needs_no_change_to_the_nodes(traced):
    bus, load = traced
    delegation_run(bus)

    class ToolNames(TraceVisitor):  # written here, in the test: nodes untouched
        def __init__(self):
            self.names = []

        def visit_tool(self, node):
            self.names.append(node.name)
            super().visit_tool(node)

    visitor = ToolNames()
    load().accept(visitor)

    assert visitor.names == ["helper", "add"]  # pre-order: the outer call, then the sub-agent's


def test_html_report_nests_runs_and_shows_costs(traced):
    bus, load = traced
    delegation_run(bus)
    report = HtmlReport()

    load().accept(report)
    page = report.page()

    assert page.startswith("<!doctype html>")
    assert page.count("<details") == 2  # main run + helper run
    assert page.index("<b>helper</b>") > page.index("<code>helper(")  # sub-run inside its tool call
    assert "$0.005000" in page  # main run's cost includes its sub-agent


def test_html_report_escapes_untrusted_text(traced):
    bus, load = traced

    class Evil(Tool):
        name = "evil"
        description = "Returns HTML."

        def run(self):
            return ToolResult("<script>alert(1)</script>")

    from miniharness.tools import PolicyChain

    box = Toolbox([Evil()], policy=PolicyChain.allow_all(), events=bus)
    Agent(MockProvider([tool("evil"), say("<img src=x onerror=alert(2)>")]), tools=box, events=bus).run("go")
    report = HtmlReport()

    load().accept(report)
    page = report.page()

    assert "<script>alert" not in page and "&lt;script&gt;" in page
    assert "<img src=x" not in page


def test_nodes_dispatch_to_the_matching_visit_method():
    calls = []

    class Recorder(TraceVisitor):
        def visit_run(self, node):
            calls.append("run")

        def visit_model(self, node):
            calls.append("model")

        def visit_tool(self, node):
            calls.append("tool")

        def visit_message(self, node):
            calls.append("message")

    r = Recorder()
    for node in (
        RunNode("a", 0, "t"),
        ModelCallNode("a", "m", "end", 0, 0, 0, None, 0.0),
        ToolCallNode("a", "t", {}, "", None, None, False),
        MessageNode("a", "b", "hi"),
    ):
        node.accept(r)

    assert calls == ["run", "model", "tool", "message"]
