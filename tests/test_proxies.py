import pytest

from miniharness import Agent, LLMResponse, Message, ToolCall
from miniharness.providers import (
    DiskCache,
    FallbackChain,
    LazyProvider,
    MockProvider,
    UsageTracker,
    lazy_provider,
)
from miniharness.tools import PolicyChain, Toolbox, ToolboxView, default_tools
from miniharness.types import Usage

HI = [Message(role="user", content="hi")]


def reply(text="ok"):
    return LLMResponse(Message(role="assistant", content=text), "end", Usage(1, 1, 0.0))


# --- LazyProvider (virtual proxy) --------------------------------------------------


def counting_factory(provider):
    built = []

    def factory():
        built.append(provider)
        return provider

    return factory, built


def test_nothing_is_built_until_first_use():
    factory, built = counting_factory(MockProvider([reply()]))
    lazy = LazyProvider(factory)

    assert built == [] and not lazy.materialized
    lazy.complete(HI, {})
    assert len(built) == 1 and lazy.materialized


def test_the_real_provider_is_built_once():
    factory, built = counting_factory(MockProvider([reply(), reply()]))
    lazy = LazyProvider(factory)

    lazy.complete(HI, {})
    lazy.complete(HI, {})

    assert len(built) == 1


def test_materialize_fails_fast_on_purpose():
    def broken():
        raise KeyError("OPENROUTER_API_KEY")

    lazy = LazyProvider(broken)  # constructing is fine

    with pytest.raises(KeyError):
        lazy.materialize()


def test_model_is_answered_without_building_when_known():
    factory, built = counting_factory(MockProvider(model="real"))

    assert LazyProvider(factory, model="known").model == "known"
    assert built == []
    assert LazyProvider(factory).model == "real"  # unknown: must build to find out


def test_lazy_provider_needs_no_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    lazy = lazy_provider("openrouter:qwen/qwen3-coder")

    assert lazy.model == "qwen/qwen3-coder"
    with pytest.raises(KeyError, match="OPENROUTER_API_KEY"):
        lazy.materialize()


def test_unused_fallback_is_never_built():
    def must_not_build():
        raise AssertionError("backup was built")

    chain = FallbackChain([MockProvider([reply("main")]), LazyProvider(must_not_build)])

    assert chain.complete(HI, {}).message.content == "main"


def test_wrapping_a_lazy_provider_in_a_cache_does_not_build_it(tmp_path):
    factory, built = counting_factory(MockProvider([reply()]))

    cache = DiskCache(UsageTracker(LazyProvider(factory)), tmp_path)

    assert built == []
    cache.complete(HI, {})
    assert cache.namespace == "MockProvider"  # unwrapped through the proxy


# --- ToolboxView (protection proxy) -------------------------------------------------------


@pytest.fixture
def toolbox(tmp_path):
    return Toolbox(default_tools(tmp_path), policy=PolicyChain.allow_all())


def call(name, **arguments):
    return ToolCall(id="c", name=name, arguments=arguments)


def test_hidden_tools_are_not_advertised(toolbox):
    view = ToolboxView(toolbox, allow={"add", "read_file"})

    assert set(view.specs()) == {"add", "read_file"}


def test_hidden_tools_look_like_missing_tools(toolbox, tmp_path):
    view = ToolboxView(toolbox, allow={"add"})

    result = view.execute(call("write_file", path="a.txt", content="x"))

    assert result == view.execute(call("does_not_exist")).replace(
        "does_not_exist", "write_file"
    )
    assert not (tmp_path / "a.txt").exists()


def test_allowed_calls_go_through_the_real_toolbox(toolbox):
    view = ToolboxView(toolbox, allow={"add"})

    assert view.execute(call("add", a=1, b=2)) == "3"
    assert [c.call.name for c in toolbox.history] == ["add"]  # shared history


def test_the_real_toolbox_policy_still_applies(tmp_path):
    strict = Toolbox(default_tools(tmp_path))  # default policy: side effects denied
    view = ToolboxView(strict, allow={"write_file"})

    assert view.execute(call("write_file", path="a.txt", content="x")).startswith(
        "Permission denied"
    )


def test_read_only_view_hides_side_effects(toolbox):
    view = ToolboxView.read_only(toolbox)

    assert set(view.specs()) == {"add", "multiply", "current_time", "read_file"}


def test_typos_in_the_allow_list_fail_at_construction(toolbox):
    with pytest.raises(ValueError, match="writefile"):
        ToolboxView(toolbox, allow={"writefile"})


def test_agent_only_offers_the_model_the_visible_tools(toolbox):
    offered = []

    class RecordingProvider(MockProvider):
        def complete(self, messages, tools):
            offered.append(set(tools))
            return super().complete(messages, tools)

    Agent(RecordingProvider([reply()]), tools=ToolboxView.read_only(toolbox)).run("hi")

    assert offered == [{"add", "multiply", "current_time", "read_file"}]
