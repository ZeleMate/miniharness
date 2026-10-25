"""Chain of Responsibility: decide whether a tool call may run.

Each policy looks at a call and either reaches a verdict or passes (None).
The chain stops at the first verdict. If nobody decides, the default applies.
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from miniharness.tools.base import Tool
from miniharness.types import ToolCall

Approver = Callable[[ToolCall], bool]


class Verdict(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"  # resolved by the chain's approver


@dataclass
class Decision:
    verdict: Verdict
    reason: str
    policy: str  # which link decided, for explaining "why was this allowed?"


class Policy(Protocol):
    def check(self, call: ToolCall, tool: Tool) -> Decision | None: ...


class PolicyChain:
    def __init__(
        self,
        policies: list[Policy],
        approver: Approver | None = None,
        default: Verdict = Verdict.DENY,
    ):
        self.policies = policies
        self.approver = approver
        self.default = default

    @classmethod
    def allow_all(cls) -> "PolicyChain":
        return cls([], default=Verdict.ALLOW)

    def decide(self, call: ToolCall, tool: Tool) -> Decision:
        decision = self._first_verdict(call, tool)
        if decision.verdict is not Verdict.ASK:
            return decision
        if self.approver is None:
            return Decision(
                Verdict.DENY,
                f"{call.name} needs approval and no approver is available",
                decision.policy,
            )
        if self.approver(call):
            return Decision(Verdict.ALLOW, f"{call.name} was approved", decision.policy)
        return Decision(
            Verdict.DENY,
            f"{call.name} needs approval and was declined",
            decision.policy,
        )

    def _first_verdict(self, call: ToolCall, tool: Tool) -> Decision:
        for policy in self.policies:
            if (decision := policy.check(call, tool)) is not None:
                return decision
        return Decision(self.default, f"no policy matched {call.name}", "default")


# --- Policies ------------------------------------------------------------------


class DenyTools:
    def __init__(self, names: set[str]):
        self.names = names

    def check(self, call: ToolCall, tool: Tool) -> Decision | None:
        if call.name in self.names:
            return Decision(
                Verdict.DENY, f"{call.name} is on the deny list", "DenyTools"
            )
        return None


class AllowTools:
    def __init__(self, names: set[str]):
        self.names = names

    def check(self, call: ToolCall, tool: Tool) -> Decision | None:
        if call.name in self.names:
            return Decision(
                Verdict.ALLOW, f"{call.name} is on the allow list", "AllowTools"
            )
        return None


class MaxCalls:
    """A quota, not a time-windowed rate limit: at most N calls per chain lifetime."""

    def __init__(self, name: str, limit: int):
        self.name = name
        self.limit = limit
        self.seen: Counter[str] = Counter()

    def check(self, call: ToolCall, tool: Tool) -> Decision | None:
        if call.name != self.name:
            return None
        if self.seen[call.name] >= self.limit:
            return Decision(
                Verdict.DENY,
                f"{call.name} reached its limit of {self.limit} calls",
                "MaxCalls",
            )
        # Counted when it passes, even if a later policy denies the call
        self.seen[call.name] += 1
        return None


class AllowReadOnly:
    def check(self, call: ToolCall, tool: Tool) -> Decision | None:
        if not tool.side_effects:
            return Decision(Verdict.ALLOW, f"{call.name} is read-only", "AllowReadOnly")
        return None


class AskBeforeSideEffects:
    def check(self, call: ToolCall, tool: Tool) -> Decision | None:
        if tool.side_effects:
            return Decision(
                Verdict.ASK, f"{call.name} changes something", "AskBeforeSideEffects"
            )
        return None


def default_policy(approver: Approver | None = None) -> PolicyChain:
    """Read-only tools run freely; anything with side effects needs approval."""
    return PolicyChain([AllowReadOnly(), AskBeforeSideEffects()], approver=approver)
