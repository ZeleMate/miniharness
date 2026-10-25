"""Factory: build a provider from a "name:model" spec string.

Provider classes add themselves with `@register_provider("name")`, so adding a
provider never means editing this file. Registration happens when the class's
module is imported, which is why `providers/__init__.py` imports every module.

Bonus stage (Singleton → dependency injection): the registry used to be a
module-level dict, a mutable singleton every caller reached for implicitly, so
tests had to monkeypatch it (D17). Now it's a plain `ProviderRegistry` class.
The built-ins live in one ordinary instance, `default_registry`, which the
convenience functions use; anything that builds providers (`build_stack`,
`lazy_provider`, `Harness`) also takes `registry=`, so a test or an
application can hand in its own and leave the default untouched:

    mine = default_registry.copy()

    @mine.register("echo")
    class EchoProvider(MockProvider): ...

    Harness("echo", registry=mine)

The default instance is still a global, but nothing *has* to use it: no
constructor reaches for it except when told nothing else (D203).
"""

from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from miniharness.providers.base import Provider

T = TypeVar("T")

ProviderFactory = Callable[..., Provider]


class ProviderRegistry:
    """Provider names → factories (usually the provider class itself)."""

    def __init__(self, providers: Mapping[str, ProviderFactory] | None = None):
        self._providers: dict[str, ProviderFactory] = {}
        for name, factory in (providers or {}).items():
            self.add(name, factory)

    def add(self, name: str, factory: ProviderFactory) -> None:
        # Duplicates raise (D18): a silent overwrite from a typo or a double import is hard to debug
        if name in self._providers:
            raise ValueError(f"Provider {name!r} is already registered")
        self._providers[name] = factory

    def register(self, name: str) -> Callable[[T], T]:
        """Decorator form of `add()`: `@registry.register("name")` on a provider class."""

        def decorator(cls: T) -> T:
            self.add(name, cls)  # type: ignore[arg-type]
            return cls

        return decorator

    def names(self) -> list[str]:
        return sorted(self._providers)

    def __contains__(self, name: object) -> bool:
        return name in self._providers

    def copy(self) -> "ProviderRegistry":
        """An independent registry with the same providers; changes to either stay apart."""
        return ProviderRegistry(self._providers)

    def create(self, spec: str, **kwargs: Any) -> Provider:
        """Create a provider from "name" or "name:model".

        Only the first colon separates the two, so model ids that contain colons
        work: "openrouter:deepseek/deepseek-chat:free". Extra kwargs (client=,
        max_tokens=, ...) go straight to the provider's constructor.
        """
        name, _, model = spec.partition(":")
        try:
            factory = self._providers[name]
        except KeyError:
            raise ValueError(
                f"Unknown provider {name!r}. Available: {', '.join(self.names())}"
            ) from None
        if model:
            kwargs["model"] = model
        return factory(**kwargs)


# The built-in providers register here when `miniharness.providers` is imported (D16)
default_registry = ProviderRegistry()


def resolve(registry: ProviderRegistry | None) -> ProviderRegistry:
    """The registry to use when a caller may or may not have injected one."""
    return default_registry if registry is None else registry


def register_provider(name: str) -> Callable[[T], T]:
    """`@register_provider("name")`: register with the default registry."""
    return default_registry.register(name)


def available_providers() -> list[str]:
    return default_registry.names()


def create_provider(spec: str, **kwargs: Any) -> Provider:
    """`default_registry.create(spec, **kwargs)`; see `ProviderRegistry.create`."""
    return default_registry.create(spec, **kwargs)
