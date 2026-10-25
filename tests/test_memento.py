import json

import pytest
from anthropic.types import TextBlock, ToolUseBlock

from miniharness import Agent, LLMResponse, Message, ToolCall
from miniharness.adapters import AnthropicMessagesAdapter
from miniharness.checkpoint import Checkpoint
from miniharness.errors import BudgetExceeded
from miniharness.lifecycle import ActingOnTools, Done, Stopped, Thinking, from_snapshot
from miniharness.providers import MockProvider
from miniharness.tools import (
    IrreversibleError,
    PolicyChain,
    Tool,
    Toolbox,
    ToolboxView,
    ToolResult,
    default_tools,
)


def tool_turn(name="add", **arguments):
    return LLMResponse(
        Message(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id=f"c-{name}", name=name, arguments=arguments or {"a": 1, "b": 2}
                )
            ],
        ),
        "tool_calls",
    )


def answer(text):
    return LLMResponse(Message(role="assistant", content=text), "end")


def write(path, content):
    return tool_turn("write_file", path=path, content=content)


@pytest.fixture
def toolbox(tmp_path):
    return Toolbox(default_tools(tmp_path), policy=PolicyChain.allow_all())


# --- Rewind the conversation -------------------------------------------------------


def test_restore_rewinds_messages_and_state():
    agent = Agent(MockProvider([tool_turn(), answer("3")]))
    agent.start("1+2?")
    cp = agent.checkpoint()  # thinking, nothing asked yet
    while not agent.done:
        agent.step()

    agent.restore(cp)

    assert isinstance(agent.state, Thinking)
    assert [m.content for m in agent.messages][1] == "1+2?"
    assert agent.model_calls == 0


def test_a_checkpoint_is_immune_to_later_changes():
    agent = Agent(MockProvider([answer("x")]))
    agent.start("task")
    cp = agent.checkpoint()

    agent.messages[1].content = "mutated"
    agent.messages.append(Message(role="user", content="extra"))

    assert cp.messages[1].content == "task" and len(cp.messages) == 2


def test_restoring_twice_gives_independent_copies():
    agent = Agent(MockProvider([]))
    agent.start("task")
    cp = agent.checkpoint()

    agent.restore(cp)
    agent.messages[1].content = "changed"
    agent.restore(cp)

    assert agent.messages[1].content == "task"


def test_resume_mid_run_with_pending_tool_calls():
    agent = Agent(MockProvider([tool_turn(), answer("3")]))
    agent.start("1+2?")
    agent.step()  # -> acting_on_tools, call not executed yet
    cp = agent.checkpoint()

    fresh = Agent(MockProvider([answer("resumed")]))  # e.g. a new process
    fresh.restore(cp, files=False)

    assert isinstance(fresh.state, ActingOnTools) and fresh.state.calls[0].name == "add"
    while not fresh.done:
        fresh.step()
    assert fresh.state.answer == "resumed"
    assert fresh.messages[-2].content == "3"  # the pending add ran after resuming


# --- Rewind file changes ---------------------------------------------------------------


def test_restore_undoes_file_changes_made_after_the_checkpoint(toolbox, tmp_path):
    agent = Agent(
        MockProvider([write("a.txt", "one"), write("b.txt", "two"), answer("done")]),
        tools=toolbox,
    )
    agent.start("write files")
    agent.step()  # model asks for a.txt
    agent.step()  # a.txt written
    cp = agent.checkpoint()
    while not agent.done:
        agent.step()  # b.txt written
    assert (tmp_path / "b.txt").exists()

    agent.restore(cp)

    assert (tmp_path / "a.txt").exists()  # before the checkpoint: kept
    assert not (tmp_path / "b.txt").exists()  # after: undone


def test_files_false_leaves_files_alone(toolbox, tmp_path):
    agent = Agent(MockProvider([write("a.txt", "x"), answer("done")]), tools=toolbox)
    agent.start("w")
    cp = agent.checkpoint()
    while not agent.done:
        agent.step()

    agent.restore(cp, files=False)

    assert (tmp_path / "a.txt").exists()


class SendEmail(Tool):
    name = "send_email"
    description = "Send an email."
    parameters = {"type": "object", "properties": {"to": {"type": "string"}}}
    side_effects = True

    def run(self, to):
        return ToolResult(f"sent to {to}")


def test_an_irreversible_action_blocks_restore_entirely(tmp_path):
    from miniharness.tools import WriteFile

    toolbox = Toolbox(
        [WriteFile(tmp_path), SendEmail()], policy=PolicyChain.allow_all()
    )
    script = [write("a.txt", "x"), tool_turn("send_email", to="boss"), answer("done")]
    agent = Agent(MockProvider(script), tools=toolbox)
    agent.start("w")
    cp = agent.checkpoint()
    while not agent.done:
        agent.step()
    messages_before = len(agent.messages)

    with pytest.raises(IrreversibleError, match="send_email"):
        agent.restore(cp)

    assert (tmp_path / "a.txt").exists()  # nothing undone
    assert len(agent.messages) == messages_before  # conversation untouched
    assert isinstance(agent.state, Done)


def test_a_view_cannot_rewind_files(toolbox, tmp_path):
    agent = Agent(MockProvider([answer("x")]), tools=ToolboxView.read_only(toolbox))
    agent.start("t")

    assert agent.checkpoint().tool_mark is None


def test_a_checkpoint_from_another_toolbox_restores_conversation_only(
    toolbox, tmp_path
):
    agent = Agent(MockProvider([answer("x")]), tools=toolbox)
    agent.start("t")
    cp = agent.checkpoint()

    other = Agent(MockProvider([]), tools=Toolbox(default_tools(tmp_path)))
    with pytest.warns(UserWarning, match="another Toolbox"):
        other.restore(cp)

    assert other.messages[1].content == "t"


# --- Save to disk and resume --------------------------------------------------------------


def test_save_and_load_round_trip(tmp_path, toolbox):
    agent = Agent(MockProvider([tool_turn(), answer("3")]), tools=toolbox)
    agent.start("1+2?")
    agent.step()
    path = tmp_path / "run.json"

    agent.checkpoint().save(path)
    loaded = Checkpoint.load(path)

    assert loaded.state == {
        "name": "acting_on_tools",
        "calls": [{"id": "c-add", "name": "add", "arguments": {"a": 1, "b": 2}}],
    }
    assert [m.role for m in loaded.messages] == ["system", "user", "assistant"]
    assert loaded.tool_mark == agent.checkpoint().tool_mark
    assert not path.with_suffix(".json.tmp").exists()


def test_anthropic_raw_blocks_are_saved_as_plain_json(tmp_path):
    raw = [
        TextBlock(type="text", text="Checking."),
        ToolUseBlock(type="tool_use", id="toolu_1", name="add", input={"a": 1, "b": 2}),
    ]
    msg = Message(
        role="assistant",
        content="Checking.",
        tool_calls=[ToolCall("toolu_1", "add", {"a": 1, "b": 2})],
        raw=raw,
    )
    cp = Checkpoint.capture(
        [Message(role="user", content="hi"), msg], {"name": "thinking"}, 1, None
    )
    path = tmp_path / "run.json"

    cp.save(path)
    saved = json.loads(path.read_text())["messages"][1]["raw"]

    assert saved == [
        {"type": "text", "text": "Checking."},
        {"type": "tool_use", "id": "toolu_1", "name": "add", "input": {"a": 1, "b": 2}},
    ]
    # ...and the adapter replays the loaded dicts unchanged
    loaded = Checkpoint.load(path)
    wire = AnthropicMessagesAdapter().to_wire(list(loaded.messages), {})
    assert wire["messages"][1]["content"] == saved


def test_a_stopped_run_survives_save_and_load(tmp_path):
    agent = Agent(MockProvider([BudgetExceeded("over")]))
    agent.run("task")
    path = tmp_path / "run.json"

    agent.checkpoint().save(path)
    fresh = Agent(MockProvider())
    fresh.restore(
        Checkpoint.load(path), files=False
    )  # another process: no history to rewind (D111)

    assert isinstance(fresh.state, Stopped)
    assert (fresh.state.reason, fresh.state.answer) == (
        "budget",
        "[stopped: budget] over",
    )


def test_an_unknown_state_is_rejected():
    with pytest.raises(ValueError, match="Unknown agent state"):
        from_snapshot({"name": "dreaming"})


def test_unknown_versions_are_rejected(tmp_path):
    path = tmp_path / "run.json"
    path.write_text(json.dumps({"version": 99}))

    with pytest.raises(ValueError, match="version"):
        Checkpoint.load(path)


# --- Fork (Prototype) -----------------------------------------------------------------------


def test_fork_continues_independently_from_the_checkpoint():
    agent = Agent(MockProvider([answer("original")]))
    agent.start("task")
    cp = agent.checkpoint()

    fork = agent.fork(
        cp, provider=MockProvider([answer("forked")]), tools=Toolbox(default_tools())
    )

    while not fork.done:
        fork.step()
    while not agent.done:
        agent.step()
    assert (fork.state.answer, agent.state.answer) == ("forked", "original")
    assert fork.messages is not agent.messages


def test_fork_keeps_the_subclass():
    class Shouty(Agent):
        def finish(self, response):
            return response.message.content.upper()

    agent = Shouty(MockProvider([]))
    agent.start("x")

    fork = agent.fork(
        provider=MockProvider([answer("hi")]), tools=Toolbox(default_tools())
    )
    while not fork.done:
        fork.step()

    assert isinstance(fork, Shouty) and fork.state.answer == "HI"


def test_fork_warns_when_sharing_the_toolbox(toolbox):
    agent = Agent(MockProvider([]), tools=toolbox)
    agent.start("x")

    with pytest.warns(UserWarning, match="shares the original's Toolbox"):
        fork = agent.fork()

    assert fork.tools is toolbox


def test_fork_never_rewinds_the_originals_files(toolbox, tmp_path):
    agent = Agent(MockProvider([write("a.txt", "x"), answer("done")]), tools=toolbox)
    agent.start("w")
    cp = agent.checkpoint()
    while not agent.done:
        agent.step()

    agent.fork(cp, tools=Toolbox(default_tools(tmp_path / "other")))

    assert (tmp_path / "a.txt").exists()


def test_fork_rejects_unknown_overrides():
    agent = Agent(MockProvider([]))
    agent.start("x")

    with pytest.raises(TypeError, match="model"):
        agent.fork(model="gpt")
