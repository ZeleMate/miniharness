import pytest

from miniharness.providers import (
    AnthropicProvider,
    MockProvider,
    OpenRouterProvider,
    available_providers,
    create_provider,
    register_provider,
)
from miniharness.providers import registry


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


def test_registering_adds_a_provider_without_editing_the_factory(monkeypatch):
    # Isolate the module-level registry so this test can't leak into others
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))

    @register_provider("echo")
    class EchoProvider(MockProvider):
        pass

    assert isinstance(create_provider("echo"), EchoProvider)


def test_duplicate_names_are_rejected(monkeypatch):
    monkeypatch.setattr(registry, "_REGISTRY", dict(registry._REGISTRY))

    with pytest.raises(ValueError, match="already registered"):
        register_provider("mock")(MockProvider)
