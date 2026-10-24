from pathlib import Path

from miniharness.tools.base import IrreversibleError, Tool, ToolCommand, ToolResult
from miniharness.tools.basic import Add, CurrentTime, Multiply
from miniharness.tools.files import ReadFile, WriteFile
from miniharness.tools.toolbox import Toolbox


def default_tools(workspace: Path | None = None) -> list[Tool]:
    """The standard tool set. File tools are included only with an explicit workspace."""
    tools: list[Tool] = [Add(), Multiply(), CurrentTime()]
    if workspace is not None:
        tools += [ReadFile(workspace), WriteFile(workspace)]
    return tools


__all__ = [
    "Add",
    "CurrentTime",
    "IrreversibleError",
    "Multiply",
    "ReadFile",
    "Tool",
    "ToolCommand",
    "ToolResult",
    "Toolbox",
    "WriteFile",
    "default_tools",
]
