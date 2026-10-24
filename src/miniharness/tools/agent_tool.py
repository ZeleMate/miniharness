"""Composite: an agent that is also a tool.

To its parent, an AgentTool is indistinguishable from `add`: it has a name, a
description, a schema, and run() returns a string. Inside, run() drives a whole
agent with its own tools, which may include more AgentTools: a tree.
"""

import copy
from typing import TYPE_CHECKING

from miniharness.events import current_depth
from miniharness.tools.base import Tool, ToolResult

if TYPE_CHECKING:
    from miniharness.agent import Agent


class AgentTool(Tool):
    parameters = {
        "type": "object",
        "properties": {"task": {"type": "string", "description": "What the sub-agent should do"}},
        "required": ["task"],
    }
    reversible = False  # a sub-agent's run isn't undone as a unit (DECISIONS.md D127)

    def __init__(self, name: str, description: str, prototype: "Agent", max_depth: int = 3):
        self.name = name
        self.description = description
        self.prototype = prototype
        self.max_depth = max_depth
        self._computing = False

    @property
    def side_effects(self) -> bool:  # type: ignore[override]
        """Derived from the sub-agent's tools, recursively (the Composite operation)."""
        if self._computing:
            return True  # a cycle (an agent that contains itself): assume the worst
        tools = getattr(self.prototype.tools, "tools", None)
        if tools is None:
            return True  # tools we can't inspect: assume the worst
        self._computing = True
        try:
            return any(tool.side_effects for tool in tools.values())
        finally:
            self._computing = False

    def run(self, task: str) -> ToolResult:  # type: ignore[override]
        depth = current_depth() + 1
        if depth > self.max_depth:
            raise RecursionError(f"{self.name} would run at depth {depth}; the limit is {self.max_depth}")
        sub = copy.copy(self.prototype)  # Prototype: same class and config, fresh run
        sub.name = self.name
        return ToolResult(sub.run(task))
