import pytest

from miniharness.providers import (
    AnthropicProvider,
    MockProvider,
    OpenRouterProvider,
    ProviderRegistry,
    available_providers,
    create_provider,
    default_registry,
)


def test_all_builtin_providers_are_registered():
    assert available_providers() == ["anthropic", "mock", "openrouter"]


def test_name_only_uses_the_provider_default_model():
    provider = create_provider("mock")

    assert isinstance(provider, MockProvider)
    assert provider.model == "mock"


def test_name_and_model():
    provider = create_provider("openrouter:qwen/qwen3-coder", client=object())

    assert isinstance(provider, OpenRouterProvider)
    assert provider.model == "qwen/qwen3-coder"


def test_only_the_first_colon_splits():
    provider = create_provider("openrouter:deepseek/deepseek-chat:free", client=object())

    assert provider.model == "deepseek/deepseek-chat:free"


def test_kwargs_pass_through_to_the_constructor():
    client = object()
    provider = create_provider("anthropic:claude-haiku-5-5", client=client, max_tokens=123)

    assert isinstance(provider, AnthropicProvider)
    assert provider.client is client
    assert provider.max_tokens == 123


def test_unknown_provider_lists_the_available_ones():
    with pytest.raises(ValueError, match="Unknown provider 'nope'. Available: anthropic, mock, openrouter"):
        create_provider("nope:model")


def test_registering_adds_a_provider_without_editing_the_factory():
    # No monkeypatch (D17 is gone): register into a copy, and the default never sees it
    mine = default_registry.copy()

    @mine.register("echo")
    class EchoProvider(MockProvider):
        pass

    assert isinstance(mine.create("echo"), EchoProvider)
    assert "echo" not in default_registry


def test_duplicate_names_are_rejected():
    with pytest.raises(ValueError, match="already registered"):
        default_registry.copy().register("mock")(MockProvider)


def test_the_builtins_live_in_the_default_registry():
    assert all(name in default_registry for name in ["anthropic", "mock", "openrouter"])
    assert available_providers() == default_registry.names()


def test_copies_are_independent_both_ways():
    a = ProviderRegistry({"mock": MockProvider})
    b = a.copy()
    b.add("other", MockProvider)
    a.add("third", MockProvider)

    assert a.names() == ["mock", "third"]
    assert b.names() == ["mock", "other"]


def test_an_empty_registry_knows_nothing():
    with pytest.raises(ValueError, match="Unknown provider 'mock'. Available: $"):
        ProviderRegistry().create("mock")


def test_a_factory_can_be_any_callable():
    registry = ProviderRegistry({"scripted": lambda model="s": MockProvider([], model=model)})

    assert registry.create("scripted:v2").model == "v2"
