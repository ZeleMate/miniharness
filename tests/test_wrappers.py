from types import SimpleNamespace as NS

import pytest

from miniharness import Agent, LLMResponse, Message
from miniharness.errors import BudgetExceeded, MalformedResponseError
from miniharness.providers import (
    AnthropicProvider,
    BudgetGuard,
    DiskCache,
    FallbackChain,
    MockProvider,
    OpenRouterProvider,
    Retry,
    UsageTracker,
)
from miniharness.types import Usage

HI = [Message(role="user", content="hi")]


def reply(text="ok", cost=0.01, tokens=(10, 5)):
    return LLMResponse(Message(role="assistant", content=text), "end", Usage(*tokens, cost_usd=cost))


# --- UsageTracker --------------------------------------------------------------


def test_tracker_sums_usage_across_calls():
    tracker = UsageTracker(MockProvider([reply(cost=0.01), reply(cost=0.02, tokens=(3, 4))]))

    tracker.complete(HI, {})
    tracker.complete(HI, {})

    assert tracker.total == Usage(13, 9, pytest.approx(0.03))
    assert len(tracker.calls) == 2


def test_unknown_cost_makes_the_total_unknown():
    tracker = UsageTracker(MockProvider([reply(cost=0.01), reply(cost=None)]))
    tracker.complete(HI, {})
    tracker.complete(HI, {})

    assert tracker.total.cost_usd is None


def test_tracker_records_the_cost_of_malformed_replies():
    bad = MalformedResponseError("bad json", Usage(10, 5, 0.01))
    tracker = UsageTracker(MockProvider([bad]))

    with pytest.raises(MalformedResponseError):
        tracker.complete(HI, {})
    assert tracker.total.cost_usd == 0.01


def test_wrappers_expose_the_inner_model():
    assert DiskCache(Retry(UsageTracker(MockProvider(model="m1"))), "/unused").model == "m1"


# --- BudgetGuard -------------------------------------------------------------------


def test_budget_allows_calls_until_the_limit_is_reached():
    tracker = UsageTracker(MockProvider([reply(cost=0.03), reply(cost=0.03), reply()]))
    guard = BudgetGuard(tracker, limit_usd=0.05)

    guard.complete(HI, {})
    guard.complete(HI, {})  # starts at $0.03 < $0.05, ends at $0.06: overshoots
    with pytest.raises(BudgetExceeded, match=r"\$0.060000 of \$0.050000"):
        guard.complete(HI, {})


def test_budget_fails_closed_when_cost_is_unknown():
    tracker = UsageTracker(MockProvider([reply(cost=None), reply()]))
    guard = BudgetGuard(tracker, limit_usd=1.0)
    guard.complete(HI, {})

    with pytest.raises(BudgetExceeded, match="unknown"):
        guard.complete(HI, {})


def test_agent_stops_gracefully_when_the_budget_runs_out():
    from miniharness.types import ToolCall

    looping = LLMResponse(
        Message(role="assistant", tool_calls=[ToolCall(id="c", name="current_time", arguments={})]),
        "tool_calls",
        Usage(10, 5, 0.03),
    )
    tracker = UsageTracker(MockProvider([looping, looping, looping]))

    answer = Agent(BudgetGuard(tracker, limit_usd=0.05)).run("loop")

    assert answer.startswith("[stopped: budget]")
    assert len(tracker.calls) == 2


# --- Retry ---------------------------------------------------------------------------


def test_retry_recovers_from_a_malformed_reply():
    retry = Retry(MockProvider([MalformedResponseError("bad"), reply("fixed")]))

    assert retry.complete(HI, {}).message.content == "fixed"
    assert retry.retries == 1


def test_retry_gives_up_after_the_last_attempt():
    retry = Retry(MockProvider([MalformedResponseError("1"), MalformedResponseError("2")]), attempts=2)

    with pytest.raises(MalformedResponseError, match="2"):
        retry.complete(HI, {})


def test_retry_ignores_other_errors():
    retry = Retry(MockProvider([ValueError("not ours"), reply()]))

    with pytest.raises(ValueError):
        retry.complete(HI, {})


def test_retry_outside_the_budget_checks_every_attempt():
    bad = MalformedResponseError("bad", Usage(10, 5, 0.05))
    tracker = UsageTracker(MockProvider([bad, reply()]))
    provider = Retry(BudgetGuard(tracker, limit_usd=0.05))

    with pytest.raises(BudgetExceeded):
        provider.complete(HI, {})
    assert len(tracker.calls) == 1  # the retry was refused before it cost anything


# --- DiskCache ---------------------------------------------------------------------------


def test_cache_replays_identical_requests(tmp_path):
    mock = MockProvider([reply("first")])
    cache = DiskCache(mock, tmp_path)

    assert cache.complete(HI, {}).message.content == "first"
    assert cache.complete(HI, {}).message.content == "first"  # mock has nothing left
    assert (cache.hits, cache.misses) == (1, 1)


def test_cache_survives_a_new_instance(tmp_path):
    DiskCache(MockProvider([reply("stored")]), tmp_path).complete(HI, {})

    again = DiskCache(MockProvider([]), tmp_path)

    assert again.complete(HI, {}).message.content == "stored"


def test_cache_key_covers_model_messages_and_tools(tmp_path):
    cache = DiskCache(MockProvider(model="a"), tmp_path)
    base = cache.key(HI, {})

    assert cache.key([Message(role="user", content="other")], {}) != base
    assert cache.key(HI, {"t": {"description": "", "parameters": {}}}) != base
    assert DiskCache(MockProvider(model="b"), tmp_path).key(HI, {}) != base


def test_cache_key_ignores_raw_provider_payloads(tmp_path):
    cache = DiskCache(MockProvider(), tmp_path)
    plain = [Message(role="assistant", content="x")]
    with_raw = [Message(role="assistant", content="x", raw=[object()])]

    assert cache.key(plain, {}) == cache.key(with_raw, {})


def test_cache_namespace_defaults_to_the_innermost_provider(tmp_path):
    assert DiskCache(Retry(UsageTracker(MockProvider())), tmp_path).namespace == "MockProvider"


# --- Stacking order --------------------------------------------------------------------------


def test_cache_outside_the_tracker_makes_hits_free(tmp_path):
    tracker = UsageTracker(MockProvider([reply(cost=0.01)]))
    provider = DiskCache(tracker, tmp_path)

    provider.complete(HI, {})
    provider.complete(HI, {})

    assert tracker.total.cost_usd == 0.01  # only the real call counted


def test_cache_inside_the_tracker_counts_hits_as_spend(tmp_path):
    tracker = UsageTracker(DiskCache(MockProvider([reply(cost=0.01)]), tmp_path))

    tracker.complete(HI, {})
    tracker.complete(HI, {})

    assert tracker.total.cost_usd == 0.02  # the replayed response's usage counted again


# --- Pricing ---------------------------------------------------------------------------------


def test_anthropic_prices_known_models():
    response = NS(content=[NS(type="text", text="hi")], stop_reason="end_turn", usage=NS(input_tokens=1_000_000, output_tokens=100_000))
    client = NS(messages=NS(create=lambda **_: response))

    usage = AnthropicProvider("claude-haiku-5-5", client).complete(HI, {}).usage

    assert usage == Usage(1_000_000, 100_000, pytest.approx(0.10 + 0.05))


def test_anthropic_unknown_model_has_unknown_cost():
    response = NS(content=[], stop_reason="end_turn", usage=NS(input_tokens=1, output_tokens=1))
    client = NS(messages=NS(create=lambda **_: response))

    assert AnthropicProvider("claude-future-9", client).complete(HI, {}).usage.cost_usd is None


def _openrouter_response(arguments):
    tc = NS(id="t", function=NS(name="add", arguments=arguments))
    return NS(
        choices=[NS(message=NS(content=None, tool_calls=[tc]), finish_reason="tool_calls")],
        usage=NS(prompt_tokens=5, completion_tokens=5, cost=6.05e-06),
    )


def test_openrouter_reads_cost_from_the_response():
    client = NS(chat=NS(completions=NS(create=lambda **_: _openrouter_response('{"a": 1, "b": 2}'))))

    assert OpenRouterProvider("m", client).complete(HI, {}).usage == Usage(5, 5, 6.05e-06)


def test_invalid_tool_json_raises_malformed_with_usage():
    client = NS(chat=NS(completions=NS(create=lambda **_: _openrouter_response('{"a": 1,'))))

    with pytest.raises(MalformedResponseError) as excinfo:
        OpenRouterProvider("m", client).complete(HI, {})
    assert excinfo.value.usage.cost_usd == 6.05e-06


# --- FallbackChain -------------------------------------------------------------------------


def refusal():
    return LLMResponse(Message(role="assistant", content="I can't help with that."), "refusal", Usage(1, 1, 0.0))


def test_fallback_uses_the_first_provider_that_answers():
    first, second = MockProvider([ConnectionError("down")]), MockProvider([reply("from second")])
    chain = FallbackChain([first, second], on=(ConnectionError,))

    assert chain.complete(HI, {}).message.content == "from second"
    assert chain.served_by is second
    assert chain.failures == [(first, "ConnectionError: down")]


def test_fallback_on_refusal():
    second = MockProvider([reply("ok")])
    chain = FallbackChain([MockProvider([refusal()]), second], on=())

    assert chain.complete(HI, {}).message.content == "ok"
    assert chain.served_by is second


def test_last_refusal_is_returned_not_raised():
    chain = FallbackChain([MockProvider([refusal()])], on=())

    assert chain.complete(HI, {}).stop_reason == "refusal"


def test_last_error_propagates():
    chain = FallbackChain([MockProvider([ConnectionError("a")]), MockProvider([ConnectionError("b")])], on=(ConnectionError,))

    with pytest.raises(ConnectionError, match="b"):
        chain.complete(HI, {})


def test_fallback_never_swallows_stop_run():
    second = MockProvider([reply()])
    chain = FallbackChain([MockProvider([BudgetExceeded("over")]), second])

    with pytest.raises(BudgetExceeded):
        chain.complete(HI, {})
    assert second.calls == []


def test_fallback_does_not_hide_programming_errors():
    chain = FallbackChain([MockProvider([KeyError("bug")]), MockProvider([reply()])])

    with pytest.raises(KeyError):
        chain.complete(HI, {})


def test_default_errors_are_transient_only():
    import anthropic
    import openai

    on = FallbackChain([MockProvider()]).on

    for sdk in (anthropic, openai):
        assert issubclass(sdk.RateLimitError, on)
        assert issubclass(sdk.InternalServerError, on)
        assert issubclass(sdk.APITimeoutError, on)
        # Configuration bugs must surface, not fall back
        assert not issubclass(sdk.AuthenticationError, on)
        assert not issubclass(sdk.BadRequestError, on)
        assert not issubclass(sdk.NotFoundError, on)
    assert issubclass(MalformedResponseError, on)
