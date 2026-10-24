"""Builder: assemble a system prompt from sections.

Sections can be added in any order, but `build()` always renders them in a
fixed order: stable sections first, volatile ones last. Prompt caching only
reuses an unchanged *prefix*, so a timestamp near the top would invalidate
everything after it on every run.
"""

from typing import Any

# Render order. Everything before ENVIRONMENT is stable across runs.
_ORDER = ("identity", "tool_rules", "instructions", "environment")
_HEADINGS = {
    "tool_rules": "Using tools",
    "instructions": "Instructions",
    "environment": "Environment",
}


class SystemPromptBuilder:
    def __init__(self) -> None:
        self._identity: str | None = None
        self._tool_rules: list[str] = []
        self._instructions: list[str] = []
        self._environment: dict[str, Any] = {}

    def identity(self, text: str) -> "SystemPromptBuilder":
        """Who the agent is. Required; calling again replaces it."""
        self._identity = text.strip()
        return self

    def tool_rules(self, *rules: str) -> "SystemPromptBuilder":
        """When and how to use tools. Schemas are sent separately by the provider."""
        self._tool_rules.extend(rules)
        return self

    def instructions(self, *rules: str) -> "SystemPromptBuilder":
        """Task or style rules. Repeated calls append."""
        self._instructions.extend(rules)
        return self

    def environment(self, **facts: Any) -> "SystemPromptBuilder":
        """Volatile facts (date, cwd, ...). Always rendered last."""
        self._environment.update(facts)
        return self

    def build(self) -> str:
        if not self._identity:
            raise ValueError("A system prompt needs an identity()")
        rendered = {
            "identity": self._identity,
            "tool_rules": _bullets(self._tool_rules),
            "instructions": _bullets(self._instructions),
            # Sorted so the same facts always render identically
            "environment": "\n".join(f"- {k}: {v}" for k, v in sorted(self._environment.items())),
        }
        parts = []
        for section in _ORDER:
            body = rendered[section]
            if not body:
                continue
            heading = _HEADINGS.get(section)
            parts.append(f"## {heading}\n{body}" if heading else body)
        return "\n\n".join(parts)


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def default_prompt() -> SystemPromptBuilder:
    """Director: the standard recipe. Returns a fresh builder to extend or build()."""
    return (
        SystemPromptBuilder()
        .identity("You are a helpful assistant.")
        .tool_rules(
            "Use the tools when they help; prefer them over mental arithmetic.",
            "When you have the final answer, reply without calling a tool.",
        )
    )
