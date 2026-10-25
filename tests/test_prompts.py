import pytest

from miniharness.prompts import SystemPromptBuilder, default_prompt


def test_renders_sections_in_fixed_order_regardless_of_call_order():
    prompt = (
        SystemPromptBuilder()
        .environment(date="2026-10-24")
        .instructions("Be brief.")
        .identity("You are a test agent.")
        .tool_rules("Use add for sums.")
        .build()
    )

    assert prompt == (
        "You are a test agent.\n\n"
        "## Using tools\n- Use add for sums.\n\n"
        "## Instructions\n- Be brief.\n\n"
        "## Environment\n- date: 2026-10-24"
    )


def test_volatile_facts_do_not_change_the_stable_prefix():
    base = lambda: SystemPromptBuilder().identity("Agent.").instructions("Be brief.")

    monday = base().environment(date="2026-10-19").build()
    tuesday = base().environment(date="2026-10-20").build()

    prefix = "Agent.\n\n## Instructions\n- Be brief.\n\n"
    assert monday.startswith(prefix) and tuesday.startswith(prefix)


def test_environment_renders_deterministically():
    a = SystemPromptBuilder().identity("A.").environment(cwd="/x", date="d").build()
    b = SystemPromptBuilder().identity("A.").environment(date="d", cwd="/x").build()

    assert a == b


def test_empty_sections_are_omitted():
    assert SystemPromptBuilder().identity("Just me.").build() == "Just me."


def test_identity_is_required():
    with pytest.raises(ValueError, match="identity"):
        SystemPromptBuilder().instructions("Be brief.").build()


def test_repeated_calls_append_rules_but_replace_identity():
    prompt = (
        SystemPromptBuilder()
        .identity("Old.")
        .identity("New.")
        .instructions("One.")
        .instructions("Two.", "Three.")
        .build()
    )

    assert prompt == "New.\n\n## Instructions\n- One.\n- Two.\n- Three."


def test_mutable_builder_is_shared_state():
    # The trade-off we accepted (DECISIONS.md D21): branching off a builder mutates it
    base = SystemPromptBuilder().identity("A.")
    base.instructions("terse")

    assert "terse" in base.build()


def test_director_returns_a_fresh_builder_each_time():
    a = default_prompt().instructions("only in a")

    assert "only in a" in a.build()
    assert "only in a" not in default_prompt().build()
