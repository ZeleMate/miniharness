import pytest

from miniharness import Agent, LLMResponse, Message, ToolCall
from miniharness.errors import BudgetExceeded, CircuitOpenError
from miniharness.lifecycle import ActingOnTools, Done, Idle, Stopped, Thinking
from miniharness.providers import CircuitBreaker, FallbackChain, MockProvider
from miniharness.types import Usage

HI = [Message(role="user", content="hi")]


def reply(text="ok"):
    return LLMResponse(Message(role="assistant", content=text), "end", Usage(1, 1, 0.0))


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def down():
    return ConnectionError("down")


def breaker(script, **kwargs):
    clock = Clock()
    b = CircuitBreaker(MockProvider(script), threshold=2, cooldown_s=30, clock=clock, on=(ConnectionError,), **kwargs)
    return b, clock


# --- Circuit breaker ----------------------------------------------------------------


def test_closed_lets_calls_through():
    b, _ = breaker([reply()])

    assert b.complete(HI, {}).message.content == "ok"
    assert b.state.name == "closed"


def test_opens_after_consecutive_failures():
    b, _ = breaker([down(), down()])

    for _ in range(2):
        with pytest.raises(ConnectionError):
            b.complete(HI, {})

    assert b.state.name == "open"
    assert b.transitions == [("closed", "open")]


def test_a_success_resets_the_failure_count():
    b, _ = breaker([down(), reply(), down()])

    for expected in (ConnectionError, None, ConnectionError):
        if expected:
            with pytest.raises(expected):
                b.complete(HI, {})
        else:
            b.complete(HI, {})

    assert b.state.name == "closed"  # never two failures in a row


def test_open_rejects_without_calling_the_provider():
    b, clock = breaker([down(), down(), reply()])
    for _ in range(2):
        with pytest.raises(ConnectionError):
            b.complete(HI, {})
    calls_before = len(b.inner.calls)

    clock.now = 10
    with pytest.raises(CircuitOpenError, match="retrying in 20s"):
        b.complete(HI, {})

    assert len(b.inner.calls) == calls_before


def test_half_open_trial_success_closes():
    b, clock = breaker([down(), down(), reply("recovered")])
    for _ in range(2):
        with pytest.raises(ConnectionError):
            b.complete(HI, {})

    clock.now = 31
    assert b.complete(HI, {}).message.content == "recovered"
    assert b.transitions == [("closed", "open"), ("open", "half_open"), ("half_open", "closed")]


def test_half_open_trial_failure_reopens_with_a_fresh_cooldown():
    b, clock = breaker([down(), down(), down()])
    for _ in range(2):
        with pytest.raises(ConnectionError):
            b.complete(HI, {})

    clock.now = 31
    with pytest.raises(ConnectionError):
        b.complete(HI, {})
    assert b.state.name == "open"

    clock.now = 40  # only 9s after re-opening
    with pytest.raises(CircuitOpenError):
        b.complete(HI, {})


def test_configuration_errors_do_not_trip_the_breaker():
    b, _ = breaker([KeyError("bad key"), KeyError("bad key"), KeyError("bad key")])

    for _ in range(3):
        with pytest.raises(KeyError):
            b.complete(HI, {})

    assert b.state.name == "closed"


def test_fallback_skips_an_open_breaker_instantly():
    clock = Clock()
    primary = MockProvider([down(), down()])
    b = CircuitBreaker(primary, threshold=2, clock=clock, on=(ConnectionError,))
    chain = FallbackChain([b, MockProvider([reply("a"), reply("b"), reply("c")])], on=(ConnectionError, CircuitOpenError))

    answers = [chain.complete(HI, {}).message.content for _ in range(3)]

    assert answers == ["a", "b", "c"]
    assert len(primary.calls) == 2  # third turn never touched the broken provider


def test_default_errors_include_circuit_open_for_fallbacks():
    assert issubclass(CircuitOpenError, FallbackChain([MockProvider()]).on)


# --- Agent lifecycle ------------------------------------------------------------------


def tool_turn():
    return LLMResponse(
        Message(role="assistant", tool_calls=[ToolCall(id="c", name="add", arguments={"a": 1, "b": 2})]),
        "tool_calls",
    )


def test_states_follow_the_conversation():
    agent = Agent(MockProvider([tool_turn(), reply("3")]))
    assert isinstance(agent.state, Idle)

    states = [agent.start("1+2?")]
    while not agent.done:
        states.append(agent.step())

    assert [type(s) for s in states] == [Thinking, ActingOnTools, Thinking, Done]
    assert agent.state.answer == "3"


def test_acting_state_carries_the_pending_calls():
    agent = Agent(MockProvider([tool_turn(), reply()]))
    agent.start("1+2?")

    acting = agent.step()

    assert [c.name for c in acting.calls] == ["add"]


def test_stop_run_ends_in_the_stopped_state():
    agent = Agent(MockProvider([BudgetExceeded("over budget")]))

    assert agent.run("x") == "[stopped: budget] over budget"
    assert isinstance(agent.state, Stopped)
    assert agent.state.reason == "budget"


def test_stepping_idle_or_terminal_agents_is_an_error():
    agent = Agent(MockProvider([reply()]))
    with pytest.raises(RuntimeError, match="idle"):
        agent.step()

    agent.run("x")
    with pytest.raises(RuntimeError, match="done"):
        agent.step()


def test_cannot_start_while_running_but_can_restart_after_done():
    agent = Agent(MockProvider([tool_turn(), reply(), reply("again")]))
    agent.start("first")
    with pytest.raises(RuntimeError, match="already running"):
        agent.start("second")

    while not agent.done:
        agent.step()
    assert agent.run("second") == "again"


def test_hooks_still_customize_the_states():
    class Shouty(Agent):
        def finish(self, response):
            return response.message.content.upper()

    assert Shouty(MockProvider([reply("hi")])).run("x") == "HI"
