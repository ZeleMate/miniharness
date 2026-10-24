import pytest

from miniharness.tools import (
    Add,
    AllowReadOnly,
    AllowTools,
    AskBeforeSideEffects,
    DenyTools,
    MaxCalls,
    PolicyChain,
    Toolbox,
    Verdict,
    WriteFile,
    default_policy,
)
from miniharness.types import ToolCall

ADD = Add()


def call(name="add", **arguments):
    return ToolCall(id="c", name=name, arguments=arguments or {"a": 1, "b": 2})


@pytest.fixture
def write(tmp_path):
    return WriteFile(tmp_path)


def write_call():
    return call("write_file", path="a.txt", content="x")


# --- The chain ------------------------------------------------------------------


def test_first_verdict_wins_and_names_the_policy():
    chain = PolicyChain([AllowTools({"add"}), DenyTools({"add"})])

    decision = chain.decide(call(), ADD)

    assert decision.verdict is Verdict.ALLOW
    assert decision.policy == "AllowTools"


def test_order_matters():
    chain = PolicyChain([DenyTools({"add"}), AllowTools({"add"})])

    assert chain.decide(call(), ADD).verdict is Verdict.DENY


def test_no_verdict_falls_back_to_deny_by_default():
    decision = PolicyChain([DenyTools({"other"})]).decide(call(), ADD)

    assert decision.verdict is Verdict.DENY
    assert decision.policy == "default"


def test_allow_all_is_an_empty_chain_that_allows():
    assert PolicyChain.allow_all().decide(call(), ADD).verdict is Verdict.ALLOW


# --- ASK and the approver ----------------------------------------------------------


def test_ask_is_resolved_by_the_approver(write):
    asked = []
    chain = PolicyChain([AskBeforeSideEffects()], approver=lambda c: asked.append(c) or True)

    assert chain.decide(write_call(), write).verdict is Verdict.ALLOW
    assert asked[0].name == "write_file"


def test_declined_ask_is_a_deny(write):
    decision = PolicyChain([AskBeforeSideEffects()], approver=lambda c: False).decide(write_call(), write)

    assert decision.verdict is Verdict.DENY
    assert "declined" in decision.reason


def test_ask_without_an_approver_fails_closed(write):
    decision = PolicyChain([AskBeforeSideEffects()]).decide(write_call(), write)

    assert decision.verdict is Verdict.DENY
    assert "no approver" in decision.reason


def test_approver_is_not_asked_when_an_earlier_policy_decides(write):
    chain = PolicyChain([DenyTools({"write_file"}), AskBeforeSideEffects()], approver=pytest.fail)

    assert chain.decide(write_call(), write).verdict is Verdict.DENY


# --- Policies --------------------------------------------------------------------------


def test_read_only_allowed_side_effects_ask(write):
    chain = default_policy(approver=lambda c: False)

    assert chain.decide(call(), ADD).verdict is Verdict.ALLOW
    assert chain.decide(write_call(), write).verdict is Verdict.DENY


def test_max_calls_denies_after_the_limit():
    chain = PolicyChain([MaxCalls("add", 2), AllowReadOnly()])

    verdicts = [chain.decide(call(), ADD).verdict for _ in range(3)]

    assert verdicts == [Verdict.ALLOW, Verdict.ALLOW, Verdict.DENY]


def test_max_calls_ignores_other_tools():
    chain = PolicyChain([MaxCalls("write_file", 0), AllowReadOnly()])

    assert chain.decide(call(), ADD).verdict is Verdict.ALLOW


# --- Toolbox integration ---------------------------------------------------------------------


def test_toolbox_denies_side_effects_by_default(tmp_path):
    box = Toolbox([WriteFile(tmp_path)])

    result = box.execute(write_call())

    assert result == "Permission denied: write_file needs approval and no approver is available"
    assert not (tmp_path / "a.txt").exists()
    assert box.history == []
    assert box.denied[0][1].policy == "AskBeforeSideEffects"


def test_toolbox_runs_approved_calls(tmp_path):
    box = Toolbox([WriteFile(tmp_path)], policy=default_policy(approver=lambda c: True))

    box.execute(write_call())

    assert (tmp_path / "a.txt").read_text() == "x"
