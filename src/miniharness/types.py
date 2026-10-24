"""Provider-neutral data types. Everything inside the harness speaks these."""

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

Role = Literal["system", "user", "assistant", "tool"]


class ToolSpec(TypedDict):
    """What a provider needs to advertise a tool to the model."""

    description: str
    parameters: dict[str, Any]  # JSON Schema for the arguments


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Message:
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None  # set when role == "tool"
    # The provider's original payload. Anthropic needs its assistant content
    # (including thinking blocks) replayed unchanged on later turns.
    raw: Any = None


@dataclass
class LLMResponse:
    message: Message
    # "end" | "tool_calls" | "max_tokens" | "refusal" | provider-specific
    stop_reason: str
