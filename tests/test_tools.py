import pytest

from miniharness.tools import (
    Add,
    IrreversibleError,
    PolicyChain,
    ReadFile,
    Tool,
    Toolbox,
    ToolResult,
    WriteFile,
    default_tools,
    files,
)
from miniharness.types import ToolCall


def call(name, **arguments):
    return ToolCall(id=f"id-{name}", name=name, arguments=arguments)


@pytest.fixture
def box(tmp_path):
    # These tests exercise execution and undo; policy has its own tests
    return Toolbox(default_tools(tmp_path), policy=PolicyChain.allow_all())


class SendEmail(Tool):
    """A side effect that can't be taken back."""

    name = "send_email"
    description = "Send an email."
    side_effects = True

    def run(self, to: str) -> ToolResult:
        return ToolResult(f"sent to {to}")


# --- Toolbox basics ----------------------------------------------------------


def test_file_tools_only_with_an_explicit_workspace(tmp_path):
    assert set(Toolbox(default_tools()).specs()) == {"add", "multiply", "current_time"}
    assert {"read_file", "write_file"} <= set(Toolbox(default_tools(tmp_path)).specs())


def test_specs_expose_description_and_schema_only():
    assert Toolbox([Add()]).specs() == {
        "add": {"description": Add.description, "parameters": Add.parameters}
    }


def test_duplicate_tool_names_are_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        Toolbox([Add(), Add()])


def test_errors_become_text_and_failed_calls_stay_out_of_history(box):
    assert box.execute(call("nope")).startswith("Error: unknown tool")
    assert box.execute(call("add", a=1)).startswith("Error: TypeError")
    assert box.history == []


def test_successful_calls_are_recorded_as_commands(box):
    assert box.execute(call("multiply", a=17, b=23)) == "391"

    [command] = box.history
    assert command.call.arguments == {"a": 17, "b": 23}
    assert command.result.output == "391"


# --- Undo --------------------------------------------------------------------


def test_undo_of_a_new_file_deletes_it(box, tmp_path):
    box.execute(call("write_file", path="a.txt", content="hello"))

    box.undo_last()

    assert not (tmp_path / "a.txt").exists()


def test_undo_of_an_overwrite_restores_previous_content(box, tmp_path):
    (tmp_path / "a.txt").write_text("original")
    box.execute(call("write_file", path="a.txt", content="changed"))

    box.undo_last()

    assert (tmp_path / "a.txt").read_text() == "original"


def test_undo_skips_read_only_commands(box, tmp_path):
    box.execute(call("write_file", path="a.txt", content="x"))
    box.execute(call("add", a=1, b=2))
    box.execute(call("read_file", path="a.txt"))

    undone = box.undo_last()

    assert undone.call.name == "write_file"
    assert not (tmp_path / "a.txt").exists()


def test_nothing_to_undo_returns_none(box):
    box.execute(call("add", a=1, b=2))

    assert box.undo_last() is None


def test_undo_all_rewinds_newest_first(box, tmp_path):
    box.execute(call("write_file", path="a.txt", content="v1"))
    box.execute(call("write_file", path="a.txt", content="v2"))
    box.execute(call("write_file", path="b.txt", content="b"))

    undone = box.undo_all()

    assert [c.call.arguments["content"] for c in undone] == ["b", "v2", "v1"]
    assert list(tmp_path.iterdir()) == []


def test_undo_stops_at_an_irreversible_side_effect(tmp_path):
    box = Toolbox([WriteFile(tmp_path), SendEmail()], policy=PolicyChain.allow_all())
    box.execute(call("write_file", path="a.txt", content="x"))
    box.execute(call("send_email", to="boss@example.com"))

    with pytest.raises(IrreversibleError, match="send_email"):
        box.undo_last()
    assert (tmp_path / "a.txt").exists()  # the older write was not touched


def test_undo_refuses_if_the_file_changed_since_it_was_written(box, tmp_path):
    box.execute(call("write_file", path="a.txt", content="ours"))
    (tmp_path / "a.txt").write_text("someone else's edit")

    with pytest.raises(RuntimeError, match="changed since"):
        box.undo_last()
    assert (tmp_path / "a.txt").read_text() == "someone else's edit"


def test_a_command_cannot_be_undone_twice(box):
    box.execute(call("write_file", path="a.txt", content="x"))
    command = box.undo_last()

    with pytest.raises(RuntimeError, match="already undone"):
        command.undo()


# --- Workspace confinement ---------------------------------------------------


@pytest.mark.parametrize(
    "path", ["../escape.txt", "sub/../../escape.txt", "/etc/passwd"]
)
def test_paths_outside_the_workspace_are_rejected(box, tmp_path, path):
    result = box.execute(call("write_file", path=path, content="x"))

    assert result.startswith("Error: PermissionError")
    assert not (tmp_path.parent / "escape.txt").exists()


def test_symlinks_pointing_outside_are_rejected(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (tmp_path / "secret.txt").write_text("secret")
    (workspace / "link.txt").symlink_to(tmp_path / "secret.txt")

    result = Toolbox([ReadFile(workspace)], policy=PolicyChain.allow_all()).execute(
        call("read_file", path="link.txt")
    )

    assert result.startswith("Error: PermissionError")


def test_write_creates_parent_directories(box, tmp_path):
    box.execute(call("write_file", path="notes/2026/today.md", content="hi"))

    assert (tmp_path / "notes/2026/today.md").read_text() == "hi"


def test_large_reads_are_truncated(box, tmp_path, monkeypatch):
    monkeypatch.setattr(files, "MAX_READ_CHARS", 10)
    (tmp_path / "big.txt").write_text("x" * 50)

    result = box.execute(call("read_file", path="big.txt"))

    assert result == "x" * 10 + "\n[truncated: file is 50 characters]"
