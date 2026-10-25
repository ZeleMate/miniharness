"""The Harness facade and the provider stack recipe it shares with the examples."""

import json

import pytest

from miniharness import Harness, LLMResponse, Message, ToolCall
from miniharness.events import RunFinished, TokenStreamed, ToolCalled
from miniharness.providers import (
    BudgetGuard,
    CircuitBreaker,
    DiskCache,
    FallbackChain,
    LazyProvider,
    MockProvider,
    ProviderRegistry,
    Retry,
    UsageTracker,
    build_stack,
    default_registry,
    lazy_provider,
)
from miniharness.tools import Add, MaxCalls, ToolboxView
from miniharness.types import Usage


def call(name, **arguments):
    return LLMResponse(
        Message(role="assistant", tool_calls=[ToolCall(id=f"c-{name}", name=name, arguments=arguments)]),
        "tool_calls",
        Usage(10, 5, cost_usd=0.01),
    )


def answer(text, cost=0.01):
    return LLMResponse(Message(role="assistant", content=text), "end", Usage(10, 5, cost_usd=cost))


def harness(script, **kwargs):
    kwargs.setdefault("console", False)
    return Harness(MockProvider(script), **kwargs)


# --- build_stack: the D46 order in one place ----------------------------------------------


def test_the_full_stack_is_built_in_the_recommended_order(tmp_path):
    stack = build_stack(MockProvider(), budget=1.0, cache=tmp_path, fallback="openrouter:some/model")

    cache = stack.provider
    assert isinstance(cache, DiskCache) and cache is stack.cache
    retry = cache.inner
    assert isinstance(retry, Retry)
    guard = retry.inner
    assert isinstance(guard, BudgetGuard)
    assert guard.inner is stack.tracker
    assert stack.tracker.inner is stack.base is stack.chain
    main, backup = stack.chain.providers
    assert isinstance(main, CircuitBreaker) and isinstance(main.inner, MockProvider)
    assert isinstance(backup, LazyProvider) and not backup.materialized  # no key needed unless used


def test_what_isnt_asked_for_is_left_out():
    base = MockProvider()
    stack = build_stack(base)

    assert isinstance(stack.provider, Retry)
    assert stack.provider.inner is stack.tracker
    assert stack.tracker.inner is base
    assert stack.chain is None and stack.cache is None


def test_a_spec_string_is_built_by_the_factory():
    stack = build_stack("mock:scripted")

    assert isinstance(stack.base, MockProvider)
    assert stack.provider.model == "scripted"


def test_cache_hits_are_free_and_dont_count_against_the_budget(tmp_path):
    hi = [Message(role="user", content="hi")]
    stack = build_stack(MockProvider([answer("ok", cost=0.01)]), budget=0.015, cache=tmp_path)

    stack.provider.complete(hi, {})
    stack.provider.complete(hi, {})  # a miss would exceed the budget and the mock is empty

    assert (stack.cache.hits, stack.cache.misses) == (1, 1)
    assert len(stack.tracker.calls) == 1


# --- the simple path ---------------------------------------------------------------------


def test_run_returns_the_answer_and_report_sums_the_calls():
    h = harness([call("add", a=2, b=3), answer("5")])

    assert h.run("2+3?") == "5"
    assert h.cost == pytest.approx(0.02)
    assert h.report() == "2 model call(s), 20 in / 10 out tokens, $0.020000"


def test_follow_up_continues_the_conversation():
    h = harness([answer("first"), answer("second")])
    h.run("one")

    assert h.follow_up("two") == "second"
    assert [m.content for m in h.agent.messages if m.role == "user"] == ["one", "two"]


def test_the_budget_is_on_by_default():
    h = harness([answer("a", cost=0.04), answer("b", cost=0.04), answer("never")])
    h.run("one")
    h.follow_up("two")

    h.follow_up("three")

    assert h.agent.state.name == "stopped"
    assert "budget" in h.agent.state.answer.lower() or "spent" in h.agent.state.answer.lower()


def test_instructions_and_workspace_go_into_the_system_prompt(tmp_path):
    h = harness([], instructions=["Be brief."], workspace=tmp_path / "ws")

    assert "- Be brief." in h.agent.system_prompt
    assert f"workspace: {tmp_path / 'ws'}" in h.agent.system_prompt
    assert (tmp_path / "ws").is_dir()


def test_a_system_prompt_replaces_the_default():
    assert harness([], system_prompt="You are terse.").agent.system_prompt == "You are terse."


# --- safe defaults: tools and approval -----------------------------------------------------


def test_file_tools_only_come_with_a_workspace(tmp_path):
    assert "write_file" not in harness([]).toolbox.tools
    assert "write_file" in harness([], workspace=tmp_path).toolbox.tools


def test_side_effects_are_denied_unless_approved(tmp_path):
    h = harness([call("write_file", path="a.txt", content="hi"), answer("tried")], workspace=tmp_path)

    h.run("write")

    assert not (tmp_path / "a.txt").exists()
    assert h.changes == []


def test_approve_true_allows_and_rewind_undoes(tmp_path):
    h = harness([call("write_file", path="a.txt", content="hi"), answer("done")], workspace=tmp_path, approve=True)

    h.run("write")
    assert (tmp_path / "a.txt").read_text() == "hi"
    assert len(h.changes) == 1

    assert len(h.rewind()) == 1
    assert not (tmp_path / "a.txt").exists()
    assert h.changes == []


def test_an_approve_callback_is_asked_with_the_call(tmp_path):
    asked = []
    h = harness(
        [call("write_file", path="a.txt", content="hi"), answer("done")],
        workspace=tmp_path,
        approve=lambda c: asked.append(c.name) or False,
    )

    h.run("write")

    assert asked == ["write_file"]
    assert not (tmp_path / "a.txt").exists()


def test_extra_policies_are_checked_before_the_defaults(tmp_path):
    script = [call("write_file", path="a.txt", content="1"), call("write_file", path="b.txt", content="2"), answer("ok")]
    h = harness(script, workspace=tmp_path, approve=True, policies=[MaxCalls("write_file", 1)])

    h.run("write twice")

    assert (tmp_path / "a.txt").exists() and not (tmp_path / "b.txt").exists()


def test_read_only_hides_tools_with_side_effects(tmp_path):
    h = harness([], workspace=tmp_path, read_only=True)

    assert isinstance(h.agent.tools, ToolboxView)
    assert "write_file" not in h.agent.tools.specs()
    assert "write_file" in h.toolbox.tools  # still reachable for the advanced case


def test_tools_replace_the_default_set():
    assert set(harness([], tools=[Add()]).toolbox.tools) == {"add"}


# --- events: one bus for everything (D98) ---------------------------------------------------


def test_tool_events_reach_the_agents_bus():
    h = harness([call("add", a=1, b=1), answer("2")])
    seen = []
    h.events.subscribe(seen.append)

    h.run("1+1")

    assert [e.call.name for e in seen if isinstance(e, ToolCalled)] == ["add"]


def test_console_prints_by_default_and_can_be_turned_off(capsys):
    harness([call("add", a=1, b=1), answer("2")], console=True).run("1+1")
    assert "add({'a': 1, 'b': 1}) -> 2" in capsys.readouterr().out

    harness([answer("2")]).run("1+1")
    assert capsys.readouterr().out == ""


def test_trace_appends_events_to_a_jsonl_file(tmp_path):
    path = tmp_path / "run.jsonl"
    harness([answer("hi")], trace=path).run("hello")

    kinds = [json.loads(line)["event"] for line in path.read_text().splitlines()]
    assert kinds[0] == "RunStarted" and kinds[-1] == "RunFinished"


# --- streaming ---------------------------------------------------------------------------


def test_stream_yields_tokens_and_mutes_the_console(capsys):
    h = harness([answer("one two three")], console=True)

    events = list(h.stream("count"))

    assert "".join(e.text for e in events if isinstance(e, TokenStreamed)) == "one two three"
    assert isinstance(events[-1], RunFinished)
    assert capsys.readouterr().out == ""  # the caller displays the run, not the printer
    assert h.agent.stream is False  # switched on for that run only


def test_the_console_comes_back_after_breaking_out_of_a_stream(capsys):
    h = harness([answer("one two three"), answer("again")], console=True, budget=None)
    for event in h.stream("count"):
        if isinstance(event, TokenStreamed):
            break
    capsys.readouterr()

    h.agent.step()  # carries on where the stream stopped

    assert h.agent.state.name == "done"
    assert capsys.readouterr().out != ""


def test_breaking_out_of_a_stream_blocks_the_next_call_under_a_budget():
    # D160: the abandoned call's cost is unknown, and a budget fails closed on unknown spend
    h = harness([answer("one two three"), answer("again")])
    for event in h.stream("count"):
        if isinstance(event, TokenStreamed):
            break

    h.agent.step()

    assert h.cost is None
    assert h.agent.state.name == "stopped"


# --- checkpoints -----------------------------------------------------------------------------


def test_a_run_stopped_by_the_budget_is_resumed_by_a_new_harness(tmp_path):
    saved = tmp_path / "run.json"
    first = harness([call("add", a=1, b=2), answer("never")], budget=0.005, checkpoint=saved)
    first.run("1+2")  # the first call costs 0.01 and blows the budget at the next check
    assert first.agent.state.name == "stopped"
    assert first.saved_run is not None

    second = harness([answer("3")], budget=1.0, checkpoint=saved)

    assert second.resume() == "3"
    assert not saved.exists()  # finished: the next run starts fresh


def test_resume_without_a_saved_run_raises(tmp_path):
    with pytest.raises(RuntimeError, match="Nothing to resume"):
        harness([], checkpoint=tmp_path / "missing.json").resume()


# --- sub-agents ------------------------------------------------------------------------------


def test_a_helper_is_a_read_only_tool_on_the_same_bus_and_budget(tmp_path):
    (tmp_path / "notes.txt").write_text("secret plans")
    provider = MockProvider(
        [
            call("researcher", task="what is in notes.txt?"),  # main agent delegates
            call("read_file", path="notes.txt"),  # helper reads
            answer("It says: secret plans"),  # helper answers
            answer("The notes are about secret plans."),  # main agent answers
        ]
    )
    h = Harness(provider, workspace=tmp_path, console=False)
    helper = h.add_helper("researcher", "Reads files and summarizes them.", ["Reply briefly."])
    seen = []
    h.events.subscribe(seen.append)

    assert h.run("what do the notes say?") == "The notes are about secret plans."
    assert "write_file" not in helper.tools.specs()
    assert {e.agent for e in seen if isinstance(e, ToolCalled)} == {"agent", "researcher"}
    assert len(h.tracker.calls) == 4


def test_a_helper_is_visible_to_a_read_only_harness(tmp_path):
    h = harness([], workspace=tmp_path, read_only=True)

    h.add_helper("researcher", "Reads files.")

    assert "researcher" in h.agent.tools.specs()


# --- registry=: providers by name without the global registry (Singleton → DI) ------------


def scripted_registry(*script):
    """A registry whose "scripted" provider replays `script`, built fresh for each test."""
    return ProviderRegistry({"scripted": lambda model="scripted": MockProvider(list(script), model=model)})


def test_harness_looks_up_specs_in_an_injected_registry():
    h = Harness("scripted:v1", registry=scripted_registry(answer("hi")), console=False)

    assert h.run("hello") == "hi"
    assert h.provider.model == "v1"
    assert "scripted" not in default_registry


def test_the_fallback_spec_uses_the_same_injected_registry():
    stack = build_stack(MockProvider(), fallback="scripted:backup", registry=scripted_registry())

    backup = stack.chain.providers[1]
    assert isinstance(backup, LazyProvider) and not backup.materialized  # still lazy (D69)
    assert backup.materialize().model == "backup"


def test_a_spec_unknown_to_the_injected_registry_fails_at_startup():
    with pytest.raises(ValueError, match="Unknown provider 'openrouter'. Available: scripted"):
        Harness("openrouter", registry=scripted_registry(), console=False)


def test_lazy_provider_builds_from_the_injected_registry_on_first_use():
    lazy = lazy_provider("scripted", registry=scripted_registry(answer("ok")))

    assert not lazy.materialized
    assert lazy.complete([Message(role="user", content="hi")], {}).message.content == "ok"
