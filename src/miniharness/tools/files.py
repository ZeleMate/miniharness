"""File tools confined to a workspace directory."""

from dataclasses import dataclass
from pathlib import Path

from miniharness.tools.base import Tool, ToolResult

MAX_READ_CHARS = 20_000  # keep one read from flooding the context window


def resolve_in_workspace(workspace: Path, path: str) -> Path:
    """Resolve `path` inside `workspace`, rejecting anything that escapes it.

    resolve() follows symlinks and `..`, so both "../../etc/passwd" and a
    symlink pointing outside the workspace are caught. Absolute paths are
    rejected too, because `workspace / "/etc"` is just "/etc".
    """
    root = workspace.resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise PermissionError(f"Path {path!r} is outside the workspace")
    return target


class ReadFile(Tool):
    name = "read_file"
    description = "Read a UTF-8 text file from the workspace."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the workspace"}
        },
        "required": ["path"],
    }

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def run(self, path: str) -> ToolResult:
        text = resolve_in_workspace(self.workspace, path).read_text(encoding="utf-8")
        if len(text) > MAX_READ_CHARS:
            text = (
                text[:MAX_READ_CHARS] + f"\n[truncated: file is {len(text)} characters]"
            )
        return ToolResult(text)


@dataclass
class _WriteUndo:
    target: Path
    previous: str | None  # None means the file did not exist
    written: str


class WriteFile(Tool):
    name = "write_file"
    description = "Create or overwrite a UTF-8 text file in the workspace."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path relative to the workspace"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }
    side_effects = True
    reversible = True

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def run(self, path: str, content: str) -> ToolResult:
        target = resolve_in_workspace(self.workspace, path)
        previous = target.read_text(encoding="utf-8") if target.exists() else None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        verb = "Overwrote" if previous is not None else "Created"
        return ToolResult(
            f"{verb} {path} ({len(content)} characters)",
            _WriteUndo(target, previous, content),
        )

    def undo(self, undo_info: _WriteUndo) -> None:
        current = (
            undo_info.target.read_text(encoding="utf-8")
            if undo_info.target.exists()
            else None
        )
        if current != undo_info.written:
            # Someone changed the file after us; restoring would destroy their edit
            raise RuntimeError(
                f"{undo_info.target.name} changed since it was written; not undoing"
            )
        if undo_info.previous is None:
            undo_info.target.unlink()
        else:
            undo_info.target.write_text(undo_info.previous, encoding="utf-8")
