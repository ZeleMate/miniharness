"""Tools the agent can call.

NAIVE ON PURPOSE: a module-level dict of plain dicts. Stage 5 turns each
tool call into a Command object; the bonus stage replaces this global
registry with dependency injection.
"""

import json
from datetime import datetime, timezone

from miniharness.types import ToolSpec


def _add(a: float, b: float) -> float:
    return a + b


def _multiply(a: float, b: float) -> float:
    return a * b


def _current_time() -> str:
    return datetime.now(timezone.utc).isoformat()


_NUMBER_PAIR = {
    "type": "object",
    "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
    "required": ["a", "b"],
}

TOOLS: dict[str, ToolSpec] = {
    "add": {
        "description": "Add two numbers.",
        "parameters": _NUMBER_PAIR,
        "fn": _add,
    },
    "multiply": {
        "description": "Multiply two numbers.",
        "parameters": _NUMBER_PAIR,
        "fn": _multiply,
    },
    "current_time": {
        "description": "Get the current UTC time as an ISO 8601 string.",
        "parameters": {"type": "object", "properties": {}},
        "fn": _current_time,
    },
}


def run_tool(name: str, arguments: dict) -> str:
    """Run a tool and return its result as a string (errors included)."""
    tool = TOOLS.get(name)
    if tool is None:
        return f"Error: unknown tool {name!r}"
    try:
        result = tool["fn"](**arguments)
    except Exception as e:  # report failures back to the model
        return f"Error: {type(e).__name__}: {e}"
    return result if isinstance(result, str) else json.dumps(result)
