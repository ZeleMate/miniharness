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
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None  # None means the cost is unknown

    def __add__(self, other: "Usage") -> "Usage":
        cost = None if self.cost_usd is None or other.cost_usd is None else self.cost_usd + other.cost_usd
        return Usage(self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens, cost)


@dataclass
class LLMResponse:
    message: Message
    # "end" | "tool_calls" | "max_tokens" | "refusal" | provider-specific
    stop_reason: str
    usage: Usage | None = None  # None means the provider reported nothing


# --- Streaming (stage 15) ------------------------------------------------------
# A provider's `stream()` yields TextDelta items as text arrives and always ends
# with exactly one Completed, carrying the same LLMResponse `complete()` returns.
# Tool-call fragments are assembled by the adapter and only appear in Completed.


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class Completed:
    response: LLMResponse


StreamChunk = TextDelta | Completed
