from pathlib import Path

from miniharness.tools.agent_tool import AgentTool
from miniharness.tools.base import IrreversibleError, Tool, ToolCommand, ToolResult
from miniharness.tools.basic import Add, CurrentTime, Multiply
from miniharness.tools.files import ReadFile, WriteFile
from miniharness.tools.policy import (
    AllowReadOnly,
    AllowTools,
    AskBeforeSideEffects,
    Decision,
    DenyTools,
    MaxCalls,
    Policy,
    PolicyChain,
    Verdict,
    default_policy,
)
from miniharness.tools.toolbox import ToolMark, Toolbox, ToolSet, execute_all
from miniharness.tools.view import ToolboxView


def default_tools(workspace: Path | None = None) -> list[Tool]:
    """The standard tool set. File tools are included only with an explicit workspace."""
    tools: list[Tool] = [Add(), Multiply(), CurrentTime()]
    if workspace is not None:
        tools += [ReadFile(workspace), WriteFile(workspace)]
    return tools


__all__ = [
    "Add",
    "AgentTool",
    "AllowReadOnly",
    "AllowTools",
    "AskBeforeSideEffects",
    "CurrentTime",
    "Decision",
    "DenyTools",
    "IrreversibleError",
    "MaxCalls",
    "Multiply",
    "Policy",
    "PolicyChain",
    "ReadFile",
    "Tool",
    "ToolCommand",
    "ToolMark",
    "ToolResult",
    "ToolSet",
    "Toolbox",
    "ToolboxView",
    "Verdict",
    "WriteFile",
    "default_policy",
    "default_tools",
    "execute_all",
]
