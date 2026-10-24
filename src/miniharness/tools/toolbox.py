"""Invoker: runs tool calls as commands and keeps their history."""

import uuid
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Protocol

from miniharness.events import EventBus, ToolCalled

from miniharness.tools.base import IrreversibleError, Tool, ToolCommand
from miniharness.tools.policy import Decision, PolicyChain, Verdict, default_policy
from miniharness.types import ToolCall, ToolSpec


class ToolSet(Protocol):
    """What the Agent needs from its tools: advertise them, and run a call."""

    def specs(self) -> dict[str, ToolSpec]: ...

    def execute(self, call: ToolCall) -> str: ...


@dataclass(frozen=True)
class ToolMark:
    """A position in one specific Toolbox's history."""

    toolbox_id: str
    position: int


class Toolbox:
    def __init__(self, tools: list[Tool], policy: PolicyChain | None = None, events: EventBus | None = None):
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.add(tool)
        # Default: read-only tools run, side effects are denied (no approver)
        self.policy = policy if policy is not None else default_policy()
        self.history: list[ToolCommand] = []
        self.denied: list[tuple[ToolCall, Decision]] = []
        self.events = events
        self.id = uuid.uuid4().hex  # lets a mark recognize the toolbox it came from

    def add(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name {tool.name!r}")
        self._tools[tool.name] = tool

    @property
    def tools(self) -> Mapping[str, Tool]:
        return MappingProxyType(self._tools)

    def specs(self) -> dict[str, ToolSpec]:
        return {
            name: {"description": tool.description, "parameters": tool.parameters}
            for name, tool in self._tools.items()
        }

    def execute(self, call: ToolCall) -> str:
        """Run a call and return what the model should see. Errors become text."""
        tool = self._tools.get(call.name)
        if tool is None:
            return self._report(call, f"Error: unknown tool {call.name!r}", None)
        decision = self.policy.decide(call, tool)
        if decision.verdict is not Verdict.ALLOW:
            self.denied.append((call, decision))
            return self._report(call, f"Permission denied: {decision.reason}", decision)
        command = ToolCommand(tool, call)
        try:
            result = command.execute()
        except Exception as e:  # report failures back to the model
            return self._report(call, f"Error: {type(e).__name__}: {e}", decision, failed=True)
        self.history.append(command)
        return self._report(call, result.output, decision)

    def _report(self, call: ToolCall, output: str, decision: Decision | None, failed: bool = False) -> str:
        if self.events is not None:
            self.events.emit(ToolCalled(call, output, decision, failed))
        return output

    def undo_last(self) -> ToolCommand | None:
        """Undo the most recent command that changed something.

        Read-only commands are skipped. Stops with IrreversibleError at an
        irreversible side effect: undoing anything older could leave the
        world inconsistent with what already happened.
        """
        for command in reversed(self.history):
            if not command.needs_undo:
                continue
            if not command.tool.reversible:
                raise IrreversibleError(
                    f"Cannot undo past {command.tool.name}({command.call.arguments})"
                )
            command.undo()
            return command
        return None

    def mark(self) -> ToolMark:
        return ToolMark(self.id, len(self.history))

    def rewind_to(self, mark: ToolMark) -> list[ToolCommand]:
        """Undo every change made after `mark`, newest first.

        Checks the whole range before touching anything: if an irreversible
        change is in the way, nothing is undone.
        """
        if mark.toolbox_id != self.id:
            raise ValueError("This mark belongs to a different Toolbox")
        pending = [c for c in reversed(self.history[mark.position :]) if c.needs_undo]
        blocking = [c for c in pending if not c.tool.reversible]
        if blocking:
            c = blocking[0]
            raise IrreversibleError(f"Cannot rewind past {c.tool.name}({c.call.arguments})")
        for command in pending:
            command.undo()
        return pending

    def undo_all(self) -> list[ToolCommand]:
        """Rewind every reversible change, newest first."""
        undone = []
        while (command := self.undo_last()) is not None:
            undone.append(command)
        return undone
