"""Provider streams: adapters, the three providers, and every wrapper's stream().

Fake SDK clients stand in for the network, like tests/test_wire_format.py.
`Scripted` replays streams that can fail part-way, which is what the
"only before the first token" rules of Retry and FallbackChain are about.
"""

from types import SimpleNamespace as NS

import openai
import pytest

from miniharness import LLMResponse, Message
from miniharness.errors import BudgetExceeded, MalformedResponseError
from miniharness.providers import (
    AnthropicProvider,
    BudgetGuard,
    CircuitBreaker,
    DiskCache,
    FallbackChain,
    LazyProvider,
    MockProvider,
    OpenRouterProvider,
    Retry,
    UsageTracker,
    collect,
    stream_from,
)
from miniharness.providers.wrappers import _Wrapper
from miniharness.types import Completed, TextDelta, ToolCall, Usage

HELLO = [Message(role="user", content="hi")]


def reply(text="ok", cost=0.01, stop="end"):
    return LLMResponse(Message(role="assistant", content=text), stop, Usage(10, 5, cost))


def texts(chunks):
    return "".join(c.text for c in chunks if isinstance(c, TextDelta))


class Scripted:
    """A streaming provider. Each script is a list of chunks; an exception in it is raised there."""

    def __init__(self, *scripts, model="scripted"):
        self.model = model
        self.scripts = list(scripts)
        self.started = 0
        self.closed = 0  # streams the consumer abandoned

    def complete(self, messages, tools):
        return collect(self.stream(messages, tools))

    def stream(self, messages, tools):
        self.started += 1
        script = self.scripts.pop(0)
        try:
            for item in script:
                if isinstance(item, Exception):
                    raise item
                yield item
        except GeneratorExit:
            self.closed += 1
            raise


def connection_error():
    return openai.APIConnectionError(request=NS(method="POST", url="x"))


# --- OpenAI-compatible stream (OpenRouter) ---------------------------------------------


def delta_chunk(content=None, tool_calls=None, finish=None):
    return NS(choices=[NS(delta=NS(content=content, tool_calls=tool_calls), finish_reason=finish)], usage=None)


def tool_fragment(index, id=None, name=None, arguments=None):
    return NS(index=index, id=id, function=NS(name=name, arguments=arguments))


def usage_chunk(cost=1e-05):
    return NS(choices=[], usage=NS(prompt_tokens=7, completion_tokens=3, cost=cost))


class FakeStream:
    """An openai `Stream`: iterable, and closable."""

    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    def __iter__(self):
        return iter(self.chunks)

    def close(self):
        self.closed = True


class FakeOpenAI:
    def __init__(self, chunks):
        self.stream = FakeStream(chunks)
        self.requests = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.stream


def test_openai_stream_yields_text_then_the_full_response():
    client = FakeOpenAI([delta_chunk("Hel"), delta_chunk("lo"), delta_chunk(finish="stop"), usage_chunk()])

    chunks = list(OpenRouterProvider("m", client).stream(HELLO, {}))

    assert chunks[:2] == [TextDelta("Hel"), TextDelta("lo")]
    final = chunks[-1].response
    assert final.message.content == "Hello"
    assert final.stop_reason == "end"
    assert final.usage == Usage(7, 3, 1e-05)  # OpenRouter's cost survives streaming
    assert client.requests[0]["stream"] is True
    assert client.requests[0]["stream_options"] == {"include_usage": True}
    assert client.stream.closed


def test_openai_stream_assembles_tool_calls_from_fragments():
    client = FakeOpenAI(
        [
            delta_chunk(tool_calls=[tool_fragment(0, id="c1", name="add", arguments="")]),
            delta_chunk(tool_calls=[tool_fragment(1, id="c2", name="current_time", arguments="{}")]),
            delta_chunk(tool_calls=[tool_fragment(0, arguments='{"a": 1, ')]),
            delta_chunk(tool_calls=[tool_fragment(0, arguments='"b": 2}')], finish="tool_calls"),
            usage_chunk(),
        ]
    )

    chunks = list(OpenRouterProvider("m", client).stream(HELLO, {}))

    assert len(chunks) == 1  # no text: fragments never leak out as chunks
    final = chunks[0].response
    assert final.stop_reason == "tool_calls"
    assert final.message.tool_calls == [
        ToolCall("c1", "add", {"a": 1, "b": 2}),
        ToolCall("c2", "current_time", {}),
    ]


def test_openai_stream_length_means_max_tokens():
    client = FakeOpenAI([delta_chunk("cut", finish="length")])

    assert collect(OpenRouterProvider("m", client).stream(HELLO, {})).stop_reason == "max_tokens"


def test_openai_stream_with_bad_tool_json_is_malformed_and_carries_usage():
    client = FakeOpenAI([delta_chunk(tool_calls=[tool_fragment(0, id="c", name="add", arguments="{oops")]), usage_chunk()])

    with pytest.raises(MalformedResponseError) as e:
        list(OpenRouterProvider("m", client).stream(HELLO, {}))
    assert e.value.usage == Usage(7, 3, 1e-05)


def test_openai_stream_is_closed_when_the_consumer_stops_early():
    client = FakeOpenAI([delta_chunk("a"), delta_chunk("b"), usage_chunk()])

    stream = OpenRouterProvider("m", client).stream(HELLO, {})
    next(stream)
    stream.close()

    assert client.stream.closed


# --- Anthropic (via the SDK's messages.stream() helper) -----------------------------------


class FakeMessageStream:
    def __init__(self, texts, final):
        self.text_stream = iter(texts)
        self._final = final
        self.exited = False

    def get_final_message(self):
        return self._final

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.exited = True


def test_anthropic_stream_yields_text_then_the_priced_response():
    blocks = [NS(type="text", text="Hi there")]
    final = NS(content=blocks, stop_reason="end_turn", usage=NS(input_tokens=1_000_000, output_tokens=0))
    manager = FakeMessageStream(["Hi", " there"], final)
    requests = []
    client = NS(messages=NS(stream=lambda **kw: requests.append(kw) or manager))

    chunks = list(AnthropicProvider("claude-haiku-5-5", client).stream(HELLO, {}))

    assert texts(chunks) == "Hi there"
    response = chunks[-1].response
    assert response.message.raw is blocks  # replayed unchanged on the next turn
    assert response.usage.cost_usd == pytest.approx(0.10)
    assert requests[0]["max_tokens"] == 16000
    assert manager.exited


# --- Mock and the helpers -------------------------------------------------------------


def test_mock_streams_word_by_word():
    chunks = list(MockProvider([reply("one two  three")]).stream(HELLO, {}))

    assert [c.text for c in chunks[:-1]] == ["one ", "two  ", "three"]
    assert isinstance(chunks[-1], Completed)


def test_stream_from_replays_complete_for_providers_without_stream():
    class OnlyComplete:
        model = "plain"

        def __init__(self):
            self.calls = 0

        def complete(self, messages, tools):
            self.calls += 1
            return reply("all at once")

    provider = OnlyComplete()
    stream = stream_from(provider, HELLO, {})
    assert provider.calls == 0  # lazy: nothing happens until the first chunk is asked for

    chunks = list(stream)
    assert chunks == [TextDelta("all at once"), Completed(chunks[-1].response)]


def test_collect_requires_a_completed_chunk():
    with pytest.raises(RuntimeError, match="without a Completed"):
        collect([TextDelta("a")])


# --- Wrappers ---------------------------------------------------------------------


def test_wrapper_default_stream_goes_through_its_own_complete():
    class Shout(_Wrapper):  # a wrapper that knows nothing about streaming
        def complete(self, messages, tools):
            r = self.inner.complete(messages, tools)
            return LLMResponse(Message(role="assistant", content=r.message.content.upper()), r.stop_reason)

    chunks = list(Shout(MockProvider([reply("quiet please")])).stream(HELLO, {}))

    assert chunks[0] == TextDelta("QUIET PLEASE")  # its behavior applied; not live, but correct


def test_tracker_records_the_usage_of_a_stream():
    tracker = UsageTracker(MockProvider([reply(cost=0.02)]))

    list(tracker.stream(HELLO, {}))

    assert tracker.calls == [Usage(10, 5, 0.02)]


def test_tracker_marks_an_abandoned_stream_as_unknown_cost_so_the_budget_fails_closed():
    tracker = UsageTracker(MockProvider([reply("many words here"), reply()]))
    budget = BudgetGuard(tracker, limit_usd=1.0)

    stream = budget.stream(HELLO, {})
    next(stream)
    stream.close()  # e.g. the user hit Ctrl-C mid-answer

    assert tracker.calls == [Usage()]
    with pytest.raises(BudgetExceeded, match="unknown"):
        list(budget.stream(HELLO, {}))


def test_budget_checks_before_the_stream_starts():
    tracker = UsageTracker(MockProvider([reply(cost=1.0), reply()]))
    budget = BudgetGuard(tracker, limit_usd=0.5)
    list(budget.stream(HELLO, {}))
    inner = tracker.inner

    with pytest.raises(BudgetExceeded):
        next(budget.stream(HELLO, {}))
    assert len(inner.calls) == 1  # the second call never reached the provider


def test_retry_restarts_a_stream_that_failed_before_any_text():
    provider = Scripted([MalformedResponseError("bad json")], [TextDelta("ok"), Completed(reply())])
    retry = Retry(provider)

    assert texts(retry.stream(HELLO, {})) == "ok"
    assert retry.retries == 1


def test_retry_does_not_restart_a_stream_that_already_showed_text():
    provider = Scripted([TextDelta("half"), MalformedResponseError("bad json")], [TextDelta("ok"), Completed(reply())])
    retry = Retry(provider)
    seen = []

    with pytest.raises(MalformedResponseError):
        for chunk in retry.stream(HELLO, {}):
            seen.append(chunk)
    assert seen == [TextDelta("half")]  # retrying would have shown "halfok"
    assert retry.retries == 0


def test_fallback_switches_before_the_first_token():
    main = Scripted([connection_error()], model="main")
    backup = Scripted([TextDelta("from backup"), Completed(reply("from backup"))], model="backup")
    chain = FallbackChain([main, backup])

    assert texts(chain.stream(HELLO, {})) == "from backup"
    assert chain.served_by is backup
    assert "APIConnectionError" in chain.failures[0][1]


def test_fallback_does_not_switch_after_text_was_shown():
    main = Scripted([TextDelta("partial"), connection_error()], model="main")
    backup = Scripted([Completed(reply())], model="backup")

    with pytest.raises(openai.APIConnectionError):
        list(FallbackChain([main, backup]).stream(HELLO, {}))
    assert backup.started == 0


def test_fallback_skips_a_refusal_that_streamed_no_text():
    main = Scripted([Completed(reply("", stop="refusal"))], model="main")
    backup = Scripted([TextDelta("sure"), Completed(reply("sure"))], model="backup")
    chain = FallbackChain([main, backup])

    assert collect(chain.stream(HELLO, {})).message.content == "sure"
    assert chain.failures[0][1] == "refusal"


def test_a_streamed_answer_after_a_skipped_refusal_includes_its_cost():
    main = Scripted([Completed(reply("", cost=0.02, stop="refusal"))], model="main")
    backup = Scripted([TextDelta("sure"), Completed(reply("sure", cost=0.01))], model="backup")

    assert collect(FallbackChain([main, backup]).stream(HELLO, {})).usage == Usage(20, 10, pytest.approx(0.03))


def test_a_streamed_malformed_reply_that_was_skipped_is_billed():
    main = Scripted([MalformedResponseError("bad json", Usage(7, 7, 0.05))], model="main")
    backup = Scripted([Completed(reply(cost=0.01))], model="backup")

    assert collect(FallbackChain([main, backup]).stream(HELLO, {})).usage.cost_usd == pytest.approx(0.06)


def test_fallback_keeps_a_refusal_whose_text_was_already_shown():
    main = Scripted([TextDelta("I can't"), Completed(reply("I can't", stop="refusal"))], model="main")
    backup = Scripted([Completed(reply())], model="backup")

    assert collect(FallbackChain([main, backup]).stream(HELLO, {})).stop_reason == "refusal"
    assert backup.started == 0


def test_breaker_counts_failed_streams_and_opens():
    provider = Scripted([connection_error()], [connection_error()])
    breaker = CircuitBreaker(provider, threshold=2)

    for _ in range(2):
        with pytest.raises(openai.APIConnectionError):
            list(breaker.stream(HELLO, {}))

    assert breaker.state.name == "open"
    with pytest.raises(Exception, match="failing"):
        next(breaker.stream(HELLO, {}))
    assert provider.started == 2


def test_breaker_ignores_a_stream_the_consumer_abandoned():
    provider = Scripted([TextDelta("a"), TextDelta("b"), Completed(reply())])
    breaker = CircuitBreaker(provider, threshold=1)

    stream = breaker.stream(HELLO, {})
    next(stream)
    stream.close()

    assert breaker.state.name == "closed"
    assert breaker.transitions == []
    assert provider.closed == 1


def test_cache_stores_a_streamed_response_and_replays_it_at_once(tmp_path):
    inner = MockProvider([reply("cached words")])
    cache = DiskCache(inner, tmp_path)

    first = list(cache.stream(HELLO, {}))
    second = list(cache.stream(HELLO, {}))

    assert len(first) == 3  # "cached ", "words", Completed
    assert second[0] == TextDelta("cached words")
    assert (cache.hits, cache.misses) == (1, 1)
    assert len(inner.calls) == 1


def test_lazy_provider_streams_and_builds_on_first_chunk():
    lazy = LazyProvider(lambda: MockProvider([reply("lazy")]), model="mock")

    stream = lazy.stream(HELLO, {})
    assert not lazy.materialized
    assert texts(stream) == "lazy"
    assert lazy.materialized


def test_wrapper_stack_streams_live_end_to_end(tmp_path):
    tracker = UsageTracker(MockProvider([reply("a b c d")]))
    provider = DiskCache(Retry(BudgetGuard(tracker, 1.0)), tmp_path)

    chunks = list(provider.stream(HELLO, {}))

    assert [c.text for c in chunks[:-1]] == ["a ", "b ", "c ", "d"]  # still word by word
    assert tracker.calls == [Usage(10, 5, 0.01)]


def test_breaker_sees_the_success_of_a_stream_consumed_by_collect_or_an_agent():
    from miniharness import Agent
    from miniharness.tools import Toolbox

    provider = Scripted([connection_error()], [TextDelta("ok"), Completed(reply())], [connection_error()],
                        [Completed(reply())])
    breaker = CircuitBreaker(provider, threshold=2)

    with pytest.raises(openai.APIConnectionError):
        collect(breaker.stream(HELLO, {}))
    collect(breaker.stream(HELLO, {}))  # resets the count...
    with pytest.raises(openai.APIConnectionError):
        Agent(breaker, tools=Toolbox([]), stream=True).run("hi")

    assert breaker.state.name == "closed"  # ...so these were never two failures in a row
    Agent(breaker, tools=Toolbox([]), stream=True).run("hi")
    assert breaker.state.failures == 0
