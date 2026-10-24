"""Exceptions shared across the harness."""

from miniharness.types import Usage


class MalformedResponseError(Exception):
    """The model replied, but the reply can't be used (e.g. invalid tool-call JSON).

    Carries the usage of the failed call: a bad reply still costs money.
    """

    def __init__(self, message: str, usage: Usage | None = None):
        super().__init__(message)
        self.usage = usage


class StopRun(Exception):
    """Raised by anything that wants the agent to end the run cleanly.

    The agent catches this one base class, so it never needs to know which
    wrapper (budget, rate limit, ...) decided to stop.
    """

    reason = "stopped"


class BudgetExceeded(StopRun):
    reason = "budget"
