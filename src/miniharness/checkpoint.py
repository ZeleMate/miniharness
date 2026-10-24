"""Memento: a snapshot of an agent that can be restored, saved and loaded.

The Agent creates checkpoints and restores from them; everyone else just
holds on to them. A checkpoint is a deep copy taken at one moment, so later
changes to the agent never leak into it (or the other way round).
"""

import copy
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from miniharness.tools import ToolMark
from miniharness.types import Message, ToolCall

FORMAT_VERSION = 1


@dataclass(frozen=True)
class Checkpoint:
    messages: tuple[Message, ...]
    state: dict[str, Any]  # from AgentState.snapshot()
    model_calls: int
    tool_mark: ToolMark | None  # None: the agent's tools can't rewind
    created_at: str

    @classmethod
    def capture(cls, messages: list[Message], state: dict[str, Any], model_calls: int, tool_mark: ToolMark | None) -> "Checkpoint":
        return cls(
            messages=tuple(copy.deepcopy(messages)),
            state=copy.deepcopy(state),
            model_calls=model_calls,
            tool_mark=tool_mark,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    # --- persistence ---------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": FORMAT_VERSION,
            "created_at": self.created_at,
            "model_calls": self.model_calls,
            "state": self.state,
            "tool_mark": None if self.tool_mark is None else vars(self.tool_mark),
            "messages": [_message_to_dict(m) for m in self.messages],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Checkpoint":
        if data.get("version") != FORMAT_VERSION:
            raise ValueError(f"Unsupported checkpoint version {data.get('version')!r}")
        mark = data["tool_mark"]
        return cls(
            messages=tuple(_message_from_dict(m) for m in data["messages"]),
            state=data["state"],
            model_calls=data["model_calls"],
            tool_mark=None if mark is None else ToolMark(**mark),
            created_at=data["created_at"],
        )

    def save(self, path: Path | str) -> None:
        path = Path(path)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(path)  # atomic: a crash mid-write never leaves half a checkpoint

    @classmethod
    def load(cls, path: Path | str) -> "Checkpoint":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _message_to_dict(m: Message) -> dict[str, Any]:
    return {
        "role": m.role,
        "content": m.content,
        "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in m.tool_calls],
        "tool_call_id": m.tool_call_id,
        "raw": _raw_to_json(m.raw),
    }


def _message_from_dict(d: dict[str, Any]) -> Message:
    return Message(
        role=d["role"],
        content=d["content"],
        tool_calls=[ToolCall(**c) for c in d["tool_calls"]],
        tool_call_id=d["tool_call_id"],
        raw=d["raw"],  # plain dicts: the Anthropic API accepts them back as content blocks
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
