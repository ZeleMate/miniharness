"""Read-only tools: no side effects, nothing to undo."""

import json
from datetime import UTC, datetime

from miniharness.tools.base import Tool, ToolResult

_NUMBER_PAIR = {
    "type": "object",
    "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
    "required": ["a", "b"],
}


class Add(Tool):
    name = "add"
    description = "Add two numbers."
    parameters = _NUMBER_PAIR

    def run(self, a: float, b: float) -> ToolResult:
        return ToolResult(json.dumps(a + b))


class Multiply(Tool):
    name = "multiply"
    description = "Multiply two numbers."
    parameters = _NUMBER_PAIR

    def run(self, a: float, b: float) -> ToolResult:
        return ToolResult(json.dumps(a * b))


class CurrentTime(Tool):
    name = "current_time"
    description = "Get the current UTC time as an ISO 8601 string."

    def run(self) -> ToolResult:
        return ToolResult(datetime.now(UTC).isoformat())
