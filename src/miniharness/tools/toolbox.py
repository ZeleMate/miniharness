"""Invoker: runs tool calls as commands and keeps their history.

Bonus stage (concurrent tools): `execute_all()` runs one turn's calls. A run of
consecutive read-only calls runs on a thread pool; a call with side effects runs
alone. Outputs, history and events still follow the model's order.
"""

import contextvars
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import groupby
from types import MappingProxyType
from typing import Protocol

from miniharness.events import EventBus, ToolCalled
from miniharness.tools.base import IrreversibleError, Tool, ToolCommand
from miniharness.tools.policy import Decision, PolicyChain, Verdict, default_policy
from miniharness.types import ToolCall, ToolSpec


class ToolSet(Protocol):
    """What the Agent needs from its tools: advertise them, and run a call.

    A tool set may also have `execute_all(calls) -> list[str]` to run a whole
    turn at once; `execute_all()` below uses it when it's there.
    """

    def specs(self) -> dict[str, ToolSpec]: ...

    def execute(self, call: ToolCall) -> str: ...


@dataclass(frozen=True)
class ToolMark:
    """A position in one specific Toolbox's history."""

    toolbox_id: str
    position: int


class Toolbox:
    def __init__(
        self,
        tools: list[Tool],
        policy: PolicyChain | None = None,
        events: EventBus | None = None,
        max_workers: int = 1,
    ):
        if max_workers < 1:
            raise ValueError(f"max_workers must be at least 1, not {max_workers}")
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.add(tool)
        # Default: read-only tools run, side effects are denied (no approver)
        self.policy = policy if policy is not None else default_policy()
        self.history: list[ToolCommand] = []
        self.denied: list[tuple[ToolCall, Decision]] = []
        self.events = events
        self.id = uuid.uuid4().hex  # lets a mark recognize the toolbox it came from
        self.max_workers = (
            max_workers  # 1: every call runs on the caller's thread (D221)
        )

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
        return self.execute_all([call])[0]

    def execute_all(self, calls: list[ToolCall]) -> list[str]:
        """Run one turn's calls and return their outputs, in the same order.

        Consecutive calls to read-only, thread-safe tools form a group that runs
        concurrently (up to `max_workers` threads); any other call is a group of
        its own. Groups run one after another (DECISIONS.md D215).
        """
        outputs: list[str] = []
        for group in self._groups(calls):
            outputs += self._run_group(group)
        return outputs

    def _groups(self, calls: list[ToolCall]) -> list[list[ToolCall]]:
        groups: list[list[ToolCall]] = []
        joinable = False  # can the next call join the last group?
        for call in calls:
            tool = self._tools.get(call.name)
            # An unknown tool runs nothing, so it never needs a group of its own. With one
            # worker there are no groups: each call is decided, run and reported in turn.
            parallel = self.max_workers > 1 and (
                tool is None or (not tool.side_effects and tool.thread_safe)
            )
            if parallel and joinable:
                groups[-1].append(call)
            else:
                groups.append([call])
            joinable = parallel
        return groups

    def _run_group(self, calls: list[ToolCall]) -> list[str]:
        # Policies decide here, in order and on this thread: they count calls and
        # may ask a human (D219). Only allowed calls become commands.
        decisions = [self._decide(call) for call in calls]
        commands = {
            i: ToolCommand(self._tools[call.name], call)
            for i, (call, decision) in enumerate(zip(calls, decisions))
            if decision is not None and decision.verdict is Verdict.ALLOW
        }
        errors = dict(zip(commands, self._run(list(commands.values()))))

        # Report in the model's order, whatever order the threads finished in (D218)
        outputs = []
        for i, (call, decision) in enumerate(zip(calls, decisions)):
            if decision is None:
                outputs.append(
                    self._report(call, f"Error: unknown tool {call.name!r}", None)
                )
            elif i not in commands:
                outputs.append(
                    self._report(
                        call, f"Permission denied: {decision.reason}", decision
                    )
                )
            elif (e := errors[i]) is not None:  # report failures back to the model
                outputs.append(
                    self._report(
                        call, f"Error: {type(e).__name__}: {e}", decision, failed=True
                    )
                )
            else:
                command = commands[i]
                self.history.append(command)
                outputs.append(self._report(call, command.result.output, decision))
        return outputs

    def _decide(self, call: ToolCall) -> Decision | None:
        """The policy's decision, or None for a tool that doesn't exist."""
        tool = self._tools.get(call.name)
        if tool is None:
            return None
        decision = self.policy.decide(call, tool)
        if decision.verdict is not Verdict.ALLOW:
            self.denied.append((call, decision))
        return decision

    def _run(self, commands: list[ToolCommand]) -> list[Exception | None]:
        """Execute the commands, concurrently when allowed; returns each one's error."""
        if len(commands) <= 1:
            return [_attempt(command) for command in commands]
        # Worker threads don't inherit ContextVars (the agent scope), so each call runs
        # in a copy of ours. Copied here, on this thread, and one per call: a context
        # can't be entered by two threads at once (D220).
        contexts = [contextvars.copy_context() for _ in commands]
        with ThreadPoolExecutor(min(self.max_workers, len(commands))) as pool:
            return list(
                pool.map(
                    lambda ctx, command: ctx.run(_attempt, command), contexts, commands
                )
            )

    def _report(
        self,
        call: ToolCall,
        output: str,
        decision: Decision | None,
        failed: bool = False,
    ) -> str:
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
            raise IrreversibleError(
                f"Cannot rewind past {c.tool.name}({c.call.arguments})"
            )
        for command in pending:
            command.undo()
        return pending

    def undo_all(self) -> list[ToolCommand]:
        """Undo changes newest first, until the history is clean or an irreversible change stops it.

        At an irreversible change, raises IrreversibleError (see `undo_last`); the newer
        changes stay undone.
        """
        undone = []
        while (command := self.undo_last()) is not None:
            undone.append(command)
        return undone


def _attempt(command: ToolCommand) -> Exception | None:
    try:
        command.execute()
    except Exception as e:  # noqa: BLE001  becomes an error message, not a crash
        return e
    return None


def execute_all(tools: ToolSet, calls: list[ToolCall]) -> list[str]:
    """Run a turn's calls through any ToolSet: as one batch if it can, else one by one."""
    batch = getattr(tools, "execute_all", None)
    if batch is not None:
        return batch(calls)
    return [tools.execute(call) for call in calls]


def execute_split(
    calls: list[ToolCall],
    handled_here: Callable[[ToolCall], bool],
    answer: Callable[[ToolCall], str],
    inner: ToolSet,
) -> list[str]:
    """For proxies: answer some calls themselves and pass the rest on.

    Each run of consecutive passed-on calls goes to `inner` as one batch, so its
    calls can still run together, and everything happens in the model's order (D221).
    """
    outputs: list[str] = []
    for here, run in groupby(calls, key=handled_here):
        run = list(run)
        outputs += [answer(call) for call in run] if here else execute_all(inner, run)
    return outputs
