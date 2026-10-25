"""Tools and the Command objects that wrap each call to them."""

from dataclasses import dataclass
from typing import Any

from miniharness.types import ToolCall


class IrreversibleError(Exception):
    """Raised when asked to undo an action that cannot be taken back."""


@dataclass
class ToolResult:
    output: str  # what the model sees
    undo_info: Any = None  # whatever undo() needs; None for read-only calls


class Tool:
    """Base class for tools. Subclasses set the class attributes and implement run().

    Defaults describe a read-only tool. A tool that changes the world sets
    `side_effects = True`, and `reversible = True` only if it implements undo().
    A read-only tool that mustn't run on two threads at once sets
    `thread_safe = False` (DECISIONS.md D216).
    """

    # Usually set as class attributes; instances may set or compute them (AgentTool)
    name: str
    description: str
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    side_effects: bool = False
    reversible: bool = False
    thread_safe: bool = True

    # `*args` too, so mypy lets each tool narrow it to its own parameters
    def run(self, *args: Any, **arguments: Any) -> ToolResult:
        raise NotImplementedError

    def undo(self, undo_info: Any) -> None:
        raise IrreversibleError(f"{self.name} cannot be undone")


@dataclass
class ToolCommand:
    """Command: one tool call, packaged with everything needed to run, log or undo it."""

    tool: Tool
    call: ToolCall
    result: ToolResult | None = None
    undone: bool = False

    def execute(self) -> ToolResult:
        self.result = self.tool.run(**self.call.arguments)
        return self.result

    def undo(self) -> None:
        if self.result is None:
            raise RuntimeError("Cannot undo a command that has not run")
        if self.undone:
            raise RuntimeError("Command already undone")
        self.tool.undo(self.result.undo_info)
        self.undone = True

    @property
    def needs_undo(self) -> bool:
        return self.tool.side_effects and not self.undone
