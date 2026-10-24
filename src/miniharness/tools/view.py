"""Protection proxy: a restricted view of a Toolbox."""

from collections.abc import Iterable

from miniharness.tools.toolbox import Toolbox
from miniharness.types import ToolCall, ToolSpec


class ToolboxView:
    """Exposes only some of a Toolbox's tools.

    Hidden tools don't appear in `specs()`, so the model never learns they
    exist, and calling one looks exactly like calling a tool that doesn't
    exist. Allowed calls go through the real Toolbox, so its policy and
    history still apply. Undo stays on the real Toolbox: the view only
    executes.
    """

    def __init__(self, toolbox: Toolbox, allow: Iterable[str]):
        allow = set(allow)
        unknown = allow - set(toolbox.tools)
        if unknown:
            raise ValueError(f"Toolbox has no tools named {sorted(unknown)}")
        self.toolbox = toolbox
        self.allow = allow

    @classmethod
    def read_only(cls, toolbox: Toolbox) -> "ToolboxView":
        return cls(toolbox, [name for name, tool in toolbox.tools.items() if not tool.side_effects])

    def specs(self) -> dict[str, ToolSpec]:
        return {name: spec for name, spec in self.toolbox.specs().items() if name in self.allow}

    def execute(self, call: ToolCall) -> str:
        if call.name not in self.allow:
            # Same message as a missing tool: don't confirm hidden tools exist
            return f"Error: unknown tool {call.name!r}"
        return self.toolbox.execute(call)
