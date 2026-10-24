"""Factory: build a provider from a "name:model" spec string.

Provider classes add themselves with `@register_provider("name")`, so adding a
provider never means editing this file. Registration happens when the class's
module is imported, which is why `providers/__init__.py` imports every module.
"""

from typing import Any, Callable, TypeVar

from miniharness.providers.base import Provider

T = TypeVar("T")

_REGISTRY: dict[str, Callable[..., Provider]] = {}


def register_provider(name: str) -> Callable[[T], T]:
    def decorator(cls: T) -> T:
        if name in _REGISTRY:
            raise ValueError(f"Provider {name!r} is already registered")
        _REGISTRY[name] = cls  # type: ignore[assignment]
        return cls

    return decorator


def available_providers() -> list[str]:
    return sorted(_REGISTRY)


def create_provider(spec: str, **kwargs: Any) -> Provider:
    """Create a provider from "name" or "name:model".

    Only the first colon separates the two, so model ids that contain colons
    work: "openrouter:deepseek/deepseek-chat:free". Extra kwargs (client=,
    max_tokens=, ...) go straight to the provider's constructor.
    """
    name, _, model = spec.partition(":")
    try:
        cls = _REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"Unknown provider {name!r}. Available: {', '.join(available_providers())}"
        ) from None
    if model:
        kwargs["model"] = model
    return cls(**kwargs)
