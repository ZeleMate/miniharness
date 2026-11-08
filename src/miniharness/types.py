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


def message_to_dict(m: Message) -> dict[str, Any]:
    return {
        "role": m.role,
        "content": m.content,
        "tool_calls": [
            {"id": c.id, "name": c.name, "arguments": c.arguments} for c in m.tool_calls
        ],
        "tool_call_id": m.tool_call_id,
        "raw": _raw_to_json(m.raw),
    }


def message_from_dict(d: dict[str, Any]) -> Message:
    return Message(
        role=d["role"],
        content=d["content"],
        tool_calls=[ToolCall(**c) for c in d["tool_calls"]],
        tool_call_id=d["tool_call_id"],
        # Plain dicts: the Anthropic API accepts them back as content blocks
        raw=d["raw"],
    )


def _raw_to_json(raw: Any) -> Any:
    """Provider payloads to plain JSON. Pydantic models (Anthropic's SDK blocks)
    are dumped; anything already JSON-shaped passes through."""
    if raw is None:
        return None
    if isinstance(raw, list):
        return [_raw_to_json(item) for item in raw]
    if hasattr(raw, "model_dump"):
        return raw.model_dump(mode="json", exclude_none=True)
    return raw


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None  # None means the cost is unknown

    def __add__(self, other: "Usage") -> "Usage":
        cost = (
            None
            if self.cost_usd is None or other.cost_usd is None
            else self.cost_usd + other.cost_usd
        )
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            cost,
        )


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
