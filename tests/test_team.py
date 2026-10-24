import io

import pytest

from miniharness import Agent, LLMResponse, Message, ToolCall
from miniharness.errors import BudgetExceeded
from miniharness.events import EventBus, MessageRouted
from miniharness.lifecycle import Done
from miniharness.observers import ConsolePrinter
from miniharness.providers import MockProvider
from miniharness.team import Team, TeamMessage
from miniharness.tools import Add, Toolbox


def tool(name, **arguments):
    return LLMResponse(
        Message(role="assistant", tool_calls=[ToolCall(id=f"c-{name}", name=name, arguments=arguments)]),
        "tool_calls",
    )


def say(text):
    return LLMResponse(Message(role="assistant", content=text), "end")


def send(to, text):
    return tool("send_message", to=to, text=text)


def review_team(writer_script, reviewer_script, **kwargs):
    writer = Agent(MockProvider(writer_script), tools=Toolbox([Add()]))
    reviewer = Agent(MockProvider(reviewer_script), tools=Toolbox([]))
    team = Team(
        members={"writer": writer, "reviewer": reviewer},
        routes={"writer": ["reviewer"], "reviewer": ["writer"]},
        finishers={"reviewer"},
        **kwargs,
    )
    return team, writer, reviewer


WRITER = [send("reviewer", "draft 1"), say("sent"), send("reviewer", "draft 2"), say("sent")]
REVIEWER = [send("writer", "line 2 is weak"), say("sent"), tool("approve"), say("done")]


# --- Agent.follow_up ------------------------------------------------------------------


def test_follow_up_continues_the_same_conversation():
    agent = Agent(MockProvider([say("first"), say("second")]))
    agent.run("one")

    agent.follow_up("two")
    while not agent.done:
        agent.step()

    assert [m.content for m in agent.messages[1:]] == ["one", "first", "two", "second"]


def test_follow_up_requires_a_finished_run():
    agent = Agent(MockProvider([]))
    with pytest.raises(RuntimeError, match="idle"):
        agent.follow_up("x")


def test_follow_up_resets_the_per_turn_step_count():
    agent = Agent(MockProvider([say("a"), say("b")]), max_steps=1)
    agent.run("one")

    agent.follow_up("two")
    agent.step()

    assert isinstance(agent.state, Done)


# --- The mediation loop ------------------------------------------------------------------


def test_review_loop_runs_until_the_reviewer_finishes():
    team, _, _ = review_team(WRITER, REVIEWER)

    assert team.run("writer", "Write a haiku.") == "draft 2"
    assert team.log == [
        TeamMessage("user", "writer", "Write a haiku."),
        TeamMessage("writer", "reviewer", "draft 1"),
        TeamMessage("reviewer", "writer", "line 2 is weak"),
        TeamMessage("writer", "reviewer", "draft 2"),
    ]


def test_each_member_sees_only_messages_sent_to_it():
    team, _, _ = review_team(WRITER, REVIEWER)
    team.run("writer", "Write a haiku.")

    writer_inbox = [m.content for m in team.members["writer"].messages if m.role == "user"]
    reviewer_inbox = [m.content for m in team.members["reviewer"].messages if m.role == "user"]
    assert writer_inbox == ["Message from user:\nWrite a haiku.", "Message from reviewer:\nline 2 is weak"]
    assert reviewer_inbox == [
        "Team task: Write a haiku.\n\nMessage from writer:\ndraft 1",  # first turn: the brief is shared
        "Message from writer:\ndraft 2",
    ]


def test_members_remember_their_own_earlier_turns():
    team, _, _ = review_team(WRITER, REVIEWER)
    team.run("writer", "Write a haiku.")

    writer_tool_calls = [tc.arguments for m in team.members["writer"].messages for tc in m.tool_calls]
    assert [a["text"] for a in writer_tool_calls] == ["draft 1", "draft 2"]  # one conversation


def test_members_never_reference_each_other():
    team, writer, _ = review_team(WRITER, REVIEWER)

    assert writer.tools is not team.members["writer"].tools  # caller's agent left untouched
    assert "send_message" not in writer.tools.specs()
    assert "reviewer" not in vars(team.members["writer"])


def test_routes_limit_who_can_message_whom():
    team, _, _ = review_team([], [])
    specs = team.members["writer"].tools.specs()

    assert specs["send_message"]["parameters"]["properties"]["to"]["enum"] == ["reviewer"]
    assert "approve" not in specs  # only the reviewer may approve
    assert team._send("writer", "boss", "hi").startswith("Error: writer cannot send")


def test_member_tools_still_work_alongside_team_tools():
    writer_script = [tool("add", a=1, b=2), send("reviewer", "3"), say("sent")]
    team, _, _ = review_team(writer_script, [tool("approve"), say("ok")])

    assert team.run("writer", "1+2?") == "3"


def test_approve_returns_the_received_draft_not_the_finishers_own_text():
    # A finisher that tries to pass its own text is ignored: approve takes no arguments
    team, _, _ = review_team(
        [send("reviewer", "the writer's draft"), say("sent")],
        [tool("approve", result="the reviewer's rewrite"), say("ok")],
    )

    assert team.run("writer", "go") == "the writer's draft"


def test_approving_before_receiving_anything_is_an_error():
    team, _, _ = review_team([], [])

    assert team._approve("reviewer").startswith("Error: there is nothing to approve")


def test_unknown_members_in_routes_are_rejected():
    with pytest.raises(ValueError, match="editor"):
        Team(members={"writer": Agent(MockProvider([]))}, routes={"writer": ["editor"]}, finishers=set())


# --- Ending without finish -------------------------------------------------------------------


def test_max_turns_stops_an_endless_conversation():
    ping = [send("reviewer", "again"), say("sent")] * 5
    pong = [send("writer", "again"), say("sent")] * 5
    team, _, _ = review_team(ping, pong, max_turns=3)

    assert team.run("writer", "go").startswith("[stopped: max_turns]")


def test_a_member_that_sends_nothing_ends_the_team():
    team, _, _ = review_team([say("I'm done, no review needed.")], [])

    assert team.run("writer", "go") == "[stopped: no messages] I'm done, no review needed."


def test_a_stopped_member_stops_the_whole_team():
    team, _, _ = review_team([send("reviewer", "d"), say("sent")], [BudgetExceeded("over")])

    assert team.run("writer", "go") == "[stopped: budget] over"


# --- Events ---------------------------------------------------------------------------------------


def test_routed_messages_are_events_and_members_are_tagged():
    bus, events, out = EventBus(), [], io.StringIO()
    bus.subscribe(events.append)
    bus.subscribe(ConsolePrinter(out))
    writer = Agent(MockProvider(WRITER), tools=Toolbox([]), events=bus)
    reviewer = Agent(MockProvider(REVIEWER), tools=Toolbox([]), events=bus)
    team = Team({"writer": writer, "reviewer": reviewer}, {"writer": ["reviewer"], "reviewer": ["writer"]}, {"reviewer"})

    team.run("writer", "Write a haiku.")

    routed = [(e.sender, e.to) for e in events if isinstance(e, MessageRouted)]
    assert routed == [("user", "writer"), ("writer", "reviewer"), ("reviewer", "writer"), ("writer", "reviewer")]
    assert {e.agent for e in events if hasattr(e, "agent") and e.agent} == {"writer", "reviewer"}
    assert "── reviewer → writer: line 2 is weak" in out.getvalue()
