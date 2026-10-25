"""The Singleton pattern, kept as a specimen, next to the dependency injection that replaced it.

`SingletonRegistry` is the textbook GoF Singleton: `__new__` hands back one shared
instance, so every caller gets the same object without anyone passing it around.
It isn't used anywhere in miniharness; these tests exist to *show* its costs.
The global registry this stage removed (D17) had the same costs, without the class.
"""

import pytest

from miniharness import Harness
from miniharness.providers import MockProvider, ProviderRegistry, default_registry


class SingletonRegistry:
    _instance: "SingletonRegistry | None" = None

    def __new__(cls) -> "SingletonRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.providers = {}
        return cls._instance

    def __init__(self):
        # __init__ still runs on every SingletonRegistry() call; resetting here would wipe
        # everyone's state, so a Singleton's __init__ must do nothing. A classic trap.
        pass


class EchoProvider(MockProvider):
    pass


@pytest.fixture
def reset_singleton():
    # The fixture a Singleton forces on every test that touches it (what D17's monkeypatch was)
    yield
    SingletonRegistry._instance = None


def test_there_is_only_one(reset_singleton):
    assert SingletonRegistry() is SingletonRegistry()


def test_a_fresh_singleton_is_not_fresh(reset_singleton):
    SingletonRegistry().providers["echo"] = EchoProvider

    # Somewhere else entirely, code that asked for "a registry" sees the change
    assert "echo" in SingletonRegistry().providers


def test_state_leaks_from_one_test_into_the_next(reset_singleton):
    # Two "tests" in a row, without the fixture between them: the second one only
    # passes because the first ran before it. Reorder or run it alone, and it fails.
    def first_test():
        SingletonRegistry().providers["leaked"] = EchoProvider

    def second_test():
        assert "leaked" in SingletonRegistry().providers

    first_test()
    second_test()


def test_the_dependency_is_invisible_in_signatures():
    # Nothing about `use()` says it needs a registry, so nothing can hand it a different one
    def use(name):
        return SingletonRegistry().providers[name]

    with pytest.raises(KeyError):
        use("echo")


# --- The same scenarios with dependency injection ------------------------------------------


def test_injected_registries_are_isolated():
    a, b = ProviderRegistry(), ProviderRegistry()
    a.add("echo", EchoProvider)

    assert "echo" in a and "echo" not in b


def test_a_test_owns_its_registry_and_needs_no_cleanup():
    mine = default_registry.copy()
    mine.add("echo", EchoProvider)

    h = Harness("echo", registry=mine, console=False)  # the dependency is a visible parameter

    assert isinstance(h.stack.base, EchoProvider)
    assert "echo" not in default_registry  # nothing to reset
