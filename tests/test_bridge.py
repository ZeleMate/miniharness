"""Bridge: agent types × providers, each side varied without touching the other."""

from types import SimpleNamespace as NS

import pytest

from miniharness import (
    Agent,
    Harness,
    LLMResponse,
    Message,
    PlannerAgent,
    ReviewerAgent,
    ToolCall,
)
from miniharness.agent_types import EXECUTE_REQUEST, REVIEW_REQUEST
from miniharness.events import EventBus, ModelCalled, StateChanged, TokenStreamed
from miniharness.providers import (
    AnthropicProvider,
    MockProvider,
    OpenRouterProvider,
    UsageTracker,
)
from miniharness.tools import Toolbox, default_tools
from miniharness.types import Usage


def call(name, **arguments):
    return LLMResponse(
        Message(
            role="assistant",
            tool_calls=[ToolCall(id=f"c-{name}", name=name, arguments=arguments)],
        ),
        "tool_calls",
        Usage(10, 5, cost_usd=0.01),
    )


def answer(text, stop_reason="end"):
    return LLMResponse(
        Message(role="assistant", content=text),
        stop_reason,
        Usage(10, 5, cost_usd=0.01),
    )


class RecordingProvider(MockProvider):
    """A MockProvider that also records which tools each call was offered."""

    def __init__(self, responses):
        super().__init__(responses)
        self.tools_offered: list[set[str]] = []

    def complete(self, messages, tools):
        self.tools_offered.append(set(tools))
        return super().complete(messages, tools)


def states(bus):
    seen = []
    bus.subscribe(lambda e: seen.append(e.new) if isinstance(e, StateChanged) else None)
    return seen


# --- PlannerAgent ---------------------------------------------------------------------------


def test_planner_plans_without_tools_then_runs_the_normal_loop():
    provider = RecordingProvider(
        [answer("1. Add the numbers."), call("add", a=2, b=3), answer("5")]
    )
    agent = PlannerAgent(provider, system_prompt="sys")
    seen = states(agent.events)

    assert agent.run("What is 2 + 3?") == "5"

    assert seen == ["planning", "thinking", "acting_on_tools", "thinking", "done"]
    assert provider.tools_offered[0] == set()  # the plan call can't act
    assert "add" in provider.tools_offered[1]
    # The planning request names the tools, since the call itself has none
    assert "- add:" in provider.calls[0][-1].content
    assert [(m.role, m.content) for m in agent.messages[:4]] == [
        ("system", "sys"),
        ("user", "What is 2 + 3?"),
        ("assistant", "1. Add the numbers."),
        ("user", EXECUTE_REQUEST),
    ]


def test_the_plan_request_is_shown_to_the_model_but_not_kept():
    provider = MockProvider([answer("plan"), answer("done")])
    agent = PlannerAgent(provider, system_prompt="sys")
    agent.run("task")

    assert (
        provider.calls[0][-1].role == "user"
        and "numbered plan" in provider.calls[0][-1].content
    )
    assert [m.role for m in agent.messages] == [
        "system",
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_a_plan_with_tool_calls_is_kept_as_text_only():
    # A provider that ignores the empty tool list must not leave an unanswered tool call behind
    sneaky = LLMResponse(
        Message(
            role="assistant",
            content="I'll add.",
            tool_calls=[ToolCall("x", "add", {"a": 1, "b": 1})],
            raw="raw",
        ),
        "tool_calls",
    )
    agent = PlannerAgent(MockProvider([sneaky, answer("2")]))
    agent.run("1 + 1?")

    plan = agent.messages[2]
    assert (plan.content, plan.tool_calls, plan.raw) == ("I'll add.", [], None)


def test_planning_counts_toward_max_steps_and_emits_model_called():
    bus = EventBus()
    calls = []
    bus.subscribe(lambda e: calls.append(e) if isinstance(e, ModelCalled) else None)
    agent = PlannerAgent(MockProvider([answer("plan"), answer("done")]), events=bus)
    agent.run("task")
    assert len(calls) == 2 and agent.model_calls == 2

    agent = PlannerAgent(
        MockProvider([answer("plan"), call("add", a=1, b=1)]), max_steps=2
    )
    with pytest.raises(RuntimeError, match="within 2 steps"):
        agent.run("task")


def test_the_plan_streams_like_any_other_model_call():
    agent = PlannerAgent(
        MockProvider([answer("Step one."), answer("Done.")]), stream=True
    )
    tokens = [e.text for e in agent.iter_run("task") if isinstance(e, TokenStreamed)]
    assert "".join(tokens) == "Step one.Done."


def test_a_planner_checkpointed_while_planning_resumes_by_planning():
    agent = PlannerAgent(MockProvider([answer("plan"), answer("done")]))
    agent.start("task")
    saved = agent.checkpoint()
    assert saved.state == {"name": "planning"}

    clone = agent.fork(
        saved,
        provider=MockProvider([answer("other plan"), answer("other")]),
        tools=Toolbox(default_tools()),
    )
    assert isinstance(clone, PlannerAgent)
    while not clone.done:
        clone.step()
    assert clone.state.answer == "other" and clone.messages[2].content == "other plan"


def test_follow_up_continues_without_a_new_plan():
    agent = PlannerAgent(
        MockProvider([answer("plan"), answer("first"), answer("second")])
    )
    agent.run("task")
    agent.follow_up("and then?")
    seen = states(agent.events)
    while not agent.done:
        agent.step()
    assert agent.state.answer == "second" and seen == ["done"]


# --- ReviewerAgent --------------------------------------------------------------------------


def test_reviewer_reviews_the_draft_once_and_returns_the_revision():
    provider = MockProvider([answer("draft"), answer("final")])
    agent = ReviewerAgent(provider)

    assert agent.run("task") == "final"
    assert provider.calls[1][-2].content == "draft"
    assert provider.calls[1][-1] == Message(role="user", content=REVIEW_REQUEST)
    assert agent.model_calls == 2


def test_the_review_round_can_use_tools():
    provider = MockProvider(
        [answer("5"), call("add", a=2, b=2), answer("4, corrected")]
    )
    agent = ReviewerAgent(provider)
    seen = states(agent.events)

    assert agent.run("What is 2 + 2?") == "4, corrected"
    assert seen == ["thinking", "thinking", "acting_on_tools", "thinking", "done"]


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal"])
def test_an_incomplete_answer_is_not_reviewed(stop_reason):
    agent = ReviewerAgent(MockProvider([answer("cut off", stop_reason)]))
    assert agent.run("task") == f"[stopped: {stop_reason}] cut off"
    assert agent.model_calls == 1


def test_each_follow_up_turn_is_reviewed_again():
    agent = ReviewerAgent(
        MockProvider([answer("d1"), answer("f1"), answer("d2"), answer("f2")])
    )
    agent.run("task")
    agent.follow_up("more")
    while not agent.done:
        agent.step()
    assert agent.state.answer == "f2"


def test_a_reviewer_restored_mid_review_does_not_review_twice():
    agent = ReviewerAgent(MockProvider([answer("draft"), answer("final")]))
    agent.start("task")
    agent.step()  # draft -> review requested
    saved = agent.checkpoint()

    clone = agent.fork(
        saved,
        provider=MockProvider([answer("final from fork")]),
        tools=Toolbox(default_tools()),
    )
    while not clone.done:
        clone.step()
    assert clone.state.answer == "final from fork"


# --- the bridge: any agent type × any provider ---------------------------------------------


class QueueClient:
    """A fake SDK client (both OpenAI and Anthropic shapes) that answers from a queue."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list[dict] = []
        self.chat = NS(completions=NS(create=self._create))
        self.messages = NS(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


def openai_text(text):
    return NS(
        choices=[NS(message=NS(content=text, tool_calls=None), finish_reason="stop")]
    )


def anthropic_text(text):
    return NS(content=[NS(type="text", text=text)], stop_reason="end_turn")


def mock(texts):
    return MockProvider([answer(t) for t in texts]), None


def openrouter(texts):
    client = QueueClient([openai_text(t) for t in texts])
    return OpenRouterProvider("some/model", client), client


def anthropic(texts):
    client = QueueClient([anthropic_text(t) for t in texts])
    return AnthropicProvider("claude-x", client), client


def tracked_mock(texts):
    return UsageTracker(MockProvider([answer(t) for t in texts])), None


@pytest.mark.parametrize("make_provider", [mock, openrouter, anthropic, tracked_mock])
@pytest.mark.parametrize("agent_type", [Agent, PlannerAgent, ReviewerAgent])
def test_every_agent_type_runs_on_every_provider(agent_type, make_provider):
    provider, client = make_provider(["first", "second"])
    agent = agent_type(provider, tools=Toolbox(default_tools()))

    result = agent.run("task")

    assert result == ("first" if agent_type is Agent else "second")
    if (
        client is not None
    ):  # the wire format is the provider's business, whatever the agent type
        assert len(client.requests) == agent.model_calls


def test_the_planning_call_goes_over_the_wire_without_tools():
    provider, client = openrouter(["plan", "done"])
    PlannerAgent(provider).run("task")
    assert "tools" not in client.requests[0] and "tools" in client.requests[1]

    provider, client = anthropic(["plan", "done"])
    PlannerAgent(provider).run("task")
    assert "tools" not in client.requests[0] and "tools" in client.requests[1]
    # Roles still alternate after planning (the plan request isn't kept)
    assert [m["role"] for m in client.requests[1]["messages"]] == [
        "user",
        "assistant",
        "user",
    ]


# --- the facade -----------------------------------------------------------------------------


def test_harness_takes_an_agent_type():
    h = Harness(
        MockProvider([answer("plan"), answer("done")]),
        agent_type=PlannerAgent,
        console=False,
    )
    assert isinstance(h.agent, PlannerAgent)
    assert h.run("task") == "done"
    assert (
        len(h.tracker.calls) == 2
    )  # the planning call is tracked and budgeted like any other


def test_helpers_stay_plain_agents():
    h = Harness(MockProvider([]), agent_type=ReviewerAgent, console=False)
    helper = h.add_helper("researcher", "Reads files.")
    assert type(helper) is Agent
