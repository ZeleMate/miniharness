"""Invoker: runs tool calls as commands and keeps their history."""

from miniharness.tools.base import IrreversibleError, Tool, ToolCommand
from miniharness.types import ToolCall, ToolSpec


class Toolbox:
    def __init__(self, tools: list[Tool]):
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"Duplicate tool name {tool.name!r}")
            self._tools[tool.name] = tool
        self.history: list[ToolCommand] = []

    def specs(self) -> dict[str, ToolSpec]:
        return {
            name: {"description": tool.description, "parameters": tool.parameters}
            for name, tool in self._tools.items()
        }

    def execute(self, call: ToolCall) -> str:
        """Run a call and return what the model should see. Errors become text."""
        tool = self._tools.get(call.name)
        if tool is None:
            return f"Error: unknown tool {call.name!r}"
        command = ToolCommand(tool, call)
        try:
            result = command.execute()
        except Exception as e:  # report failures back to the model
            return f"Error: {type(e).__name__}: {e}"
        self.history.append(command)
        return result.output

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

    def undo_all(self) -> list[ToolCommand]:
        """Rewind every reversible change, newest first."""
        undone = []
        while (command := self.undo_last()) is not None:
            undone.append(command)
        return undone
