import io

from miniharness import Agent, LLMResponse, Message, ToolCall
from miniharness.events import EventBus, RunStarted, ToolCalled, current_depth
from miniharness.observers import ConsolePrinter
from miniharness.providers import MockProvider
from miniharness.tools import (
    Add,
    AgentTool,
    PolicyChain,
    ReadFile,
    Toolbox,
    ToolboxView,
    WriteFile,
    default_policy,
)


def call(name, **arguments):
    return LLMResponse(
        Message(role="assistant", tool_calls=[ToolCall(id=f"c-{name}", name=name, arguments=arguments)]),
        "tool_calls",
    )


def answer(text):
    return LLMResponse(Message(role="assistant", content=text), "end")


def make_sub(script, tools=None, events=None):
    return Agent(MockProvider(script), tools=tools or Toolbox([Add()]), events=events)


# --- A sub-agent is just a tool -------------------------------------------------------


def test_parent_calls_a_sub_agent_like_any_tool():
    helper = AgentTool("helper", "Adds numbers.", make_sub([call("add", a=2, b=3), answer("five")]))
    parent = Agent(MockProvider([call("helper", task="2+3?"), answer("The helper says five.")]), tools=Toolbox([helper]))

    assert parent.run("ask the helper") == "The helper says five."
    assert parent.messages[3].content == "five"  # the sub-agent's answer is the tool result


def test_only_the_answer_reaches_the_parent_context():
    helper = AgentTool("helper", "h", make_sub([call("add", a=2, b=3), answer("five")]))
    parent = Agent(MockProvider([call("helper", task="2+3?"), answer("ok")]), tools=Toolbox([helper]))

    parent.run("x")

    assert len(parent.messages) == 5  # system, user, call, result, answer: no sub-agent turns


def test_each_call_gets_a_fresh_sub_agent():
    prototype = make_sub([answer("first"), answer("second")])
    helper = AgentTool("helper", "h", prototype)

    helper.run("one")
    helper.run("two")

    assert prototype.messages == []  # the prototype itself never runs
    assert prototype.provider.calls[1][1].content == "two"  # second run started clean


def test_sub_agents_can_nest():
    leaf = AgentTool("leaf", "l", make_sub([answer("from the leaf")]))
    middle = AgentTool("middle", "m", make_sub([call("leaf", task="go"), answer("middle got it")], tools=Toolbox([leaf])))
    root = Agent(MockProvider([call("middle", task="go"), answer("root done")]), tools=Toolbox([middle]))

    assert root.run("go") == "root done"


# --- Side effects are derived recursively ---------------------------------------------------


def test_read_only_sub_agent_is_read_only(tmp_path):
    view = ToolboxView.read_only(Toolbox([ReadFile(tmp_path), WriteFile(tmp_path)]))

    assert AgentTool("reader", "r", make_sub([], tools=view)).side_effects is False


def test_a_writing_sub_agent_has_side_effects(tmp_path):
    assert AgentTool("writer", "w", make_sub([], tools=Toolbox([WriteFile(tmp_path)]))).side_effects is True


def test_side_effects_propagate_up_the_tree(tmp_path):
    writer = AgentTool("writer", "w", make_sub([], tools=Toolbox([WriteFile(tmp_path)])))
    manager = AgentTool("manager", "m", make_sub([], tools=Toolbox([Add(), writer])))

    assert manager.side_effects is True


def test_policies_treat_sub_agents_by_their_derived_side_effects(tmp_path):
    reader = AgentTool("reader", "r", make_sub([answer("read it")], tools=Toolbox([ReadFile(tmp_path)])))
    writer = AgentTool("writer", "w", make_sub([answer("wrote it")], tools=Toolbox([WriteFile(tmp_path)])))
    box = Toolbox([reader, writer], policy=default_policy(approver=None))

    assert box.execute(ToolCall("1", "reader", {"task": "x"})) == "read it"  # AllowReadOnly
    assert box.execute(ToolCall("2", "writer", {"task": "x"})).startswith("Permission denied")


def test_a_cycle_is_treated_as_having_side_effects():
    toolbox = Toolbox([])
    selfish = AgentTool("selfish", "s", Agent(MockProvider([]), tools=toolbox))
    toolbox.add(selfish)  # an agent that contains itself

    assert selfish.side_effects is True


# --- Depth -------------------------------------------------------------------------------------


def test_depth_limit_stops_runaway_recursion():
    toolbox = Toolbox([], policy=PolicyChain.allow_all())
    script = [call("again", task="deeper")] * 10 + [answer("bottom")] * 10
    again = AgentTool("again", "recurse", Agent(MockProvider(script), tools=toolbox), max_depth=2)
    toolbox.add(again)

    result = Agent(MockProvider([call("again", task="go"), answer("stopped")]), tools=toolbox).run("go")

    assert result == "stopped"
    assert current_depth() == -1  # scopes were all unwound


# --- Events: one bus, tagged with depth ---------------------------------------------------------


def test_events_are_tagged_with_agent_and_depth():
    bus, events = EventBus(), []
    bus.subscribe(events.append)
    sub_box = Toolbox([Add()], events=bus)
    helper = AgentTool("helper", "h", make_sub([call("add", a=1, b=1), answer("two")], tools=sub_box, events=bus))
    parent = Agent(MockProvider([call("helper", task="1+1"), answer("ok")]), tools=Toolbox([helper], events=bus), events=bus, name="main")

    parent.run("go")

    started = [(e.agent, e.depth) for e in events if isinstance(e, RunStarted)]
    tools = [(e.call.name, e.agent, e.depth) for e in events if isinstance(e, ToolCalled)]
    assert started == [("main", 0), ("helper", 1)]
    assert tools == [("add", "helper", 1), ("helper", "main", 0)]  # inner call finishes first


def test_tool_calls_through_a_shared_toolbox_are_attributed_to_the_caller(tmp_path):
    bus, events = EventBus(), []
    bus.subscribe(events.append)
    shared = Toolbox([ReadFile(tmp_path), Add()], policy=PolicyChain.allow_all(), events=bus)
    reader = AgentTool("reader", "r", make_sub([call("add", a=1, b=2), answer("3")], tools=ToolboxView(shared, {"add"}), events=bus))
    shared.add(reader)

    Agent(MockProvider([call("reader", task="1+2"), answer("ok")]), tools=ToolboxView(shared, {"reader"}), events=bus, name="main").run("go")

    add_event = next(e for e in events if isinstance(e, ToolCalled) and e.call.name == "add")
    assert (add_event.agent, add_event.depth) == ("reader", 1)


def test_console_printer_indents_sub_agents():
    bus = EventBus()
    out = io.StringIO()
    bus.subscribe(ConsolePrinter(out))
    helper = AgentTool("helper", "h", make_sub([answer("done")], events=bus))
    Agent(MockProvider([call("helper", task="do it"), answer("ok")]), tools=Toolbox([helper], events=bus), events=bus).run("go")

    lines = out.getvalue().splitlines()
    assert "    helper started: do it" in lines
    assert "    [done]" in lines  # sub-agent, depth 1
    assert "  [done]" in lines  # parent, depth 0
