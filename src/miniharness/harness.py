"""Facade: one object that builds a capable agent and runs it.

Stage 16 (Facade): a capable agent is a provider wrapped in five layers, a
Toolbox with a policy chain and an approver, an event bus shared by the agent
and its tools, a system prompt from a builder, and optionally checkpoints and
sub-agents. `Harness` composes all of that from a few keyword arguments with
safe defaults:

    h = Harness("openrouter", budget=0.05, workspace="ws", approve=True)
    print(h.run("Write a haiku to haiku.txt"))
    print(h.report())

A facade simplifies; it doesn't lock anything away. Every subsystem it built
stays a public attribute (`agent`, `toolbox`, `stack`, `tracker`, `events`),
so the advanced case starts from the facade instead of from scratch.
"""

import os
from collections.abc import Callable, Iterator, Sequence
from datetime import date
from pathlib import Path

from miniharness.agent import Agent
from miniharness.checkpoint import Checkpoint
from miniharness.events import Event, EventBus, RunFinished, StateChanged
from miniharness.observers import ConsolePrinter, JsonlTracer
from miniharness.prompts import default_prompt
from miniharness.providers import Provider, UsageTracker, build_stack
from miniharness.tools import AgentTool, Policy, Tool, Toolbox, ToolboxView, ToolCommand, default_policy, default_tools
from miniharness.types import ToolCall

Approve = bool | Callable[[ToolCall], bool] | None


class Harness:
    def __init__(
        self,
        model: str | Provider = "openrouter",
        *,
        budget: float | None = 0.05,
        cache: bool | str | Path = False,
        fallback: str | Provider | None = None,
        workspace: str | Path | None = None,
        approve: Approve = None,
        policies: Sequence[Policy] = (),
        read_only: bool = False,
        tools: list[Tool] | None = None,
        instructions: Sequence[str] = (),
        system_prompt: str | None = None,
        events: EventBus | None = None,
        console: bool = True,
        trace: str | Path | None = None,
        checkpoint: str | Path | None = None,
        stream: bool = False,
        max_steps: int = 10,
    ):
        """Every argument has a safe default; only `model` is usually worth setting.

        - `budget`: USD limit for this harness (None: no limit). Unknown cost fails closed (D48).
        - `cache`: True for `.cache/llm`, or a directory. Development only (pickle).
        - `workspace`: file tools are added only when one is given, sandboxed to it.
        - `approve`: tools with side effects are denied unless this is True or a callback (D176).
        - `policies`: extra policies checked before the default read-only/ask chain.
        - `tools`: replaces the default tool set (the workspace's file tools included).
        - `console` / `trace`: print events live / append them to a JSONL file.
        - `checkpoint`: autosave the run here after every step; see `resume()`.
        """
        self.stack = build_stack(
            model,
            budget=budget,
            cache=Path(".cache/llm") if cache is True else (cache or None),
            fallback=fallback,
        )
        self.events = events if events is not None else EventBus()
        self._console = ConsolePrinter() if console else None
        self._muted = False
        if self._console is not None:
            self.events.subscribe(lambda event: None if self._muted else self._console(event))
        if trace is not None:
            self.events.subscribe(JsonlTracer(trace))

        self.workspace = Path(workspace) if workspace is not None else None
        if self.workspace is not None:
            self.workspace.mkdir(parents=True, exist_ok=True)
        policy = default_policy(approver=_approver(approve))
        policy.policies[:0] = list(policies)
        # One bus for the agent and its tools, so ToolCalled is never silently lost (D98)
        self.toolbox = Toolbox(
            tools if tools is not None else default_tools(self.workspace), policy=policy, events=self.events
        )
        self.read_only = read_only

        if system_prompt is None:
            builder = default_prompt().instructions(*instructions)
            facts = {"date": date.today().isoformat(), "cwd": os.getcwd()}
            if self.workspace is not None:
                facts["workspace"] = str(self.workspace)
            system_prompt = builder.environment(**facts).build()
        self.agent = Agent(
            self.provider,
            system_prompt=system_prompt,
            tools=self._visible_tools(),
            max_steps=max_steps,
            events=self.events,
            stream=stream,
        )

        self.checkpoint_path = Path(checkpoint) if checkpoint is not None else None
        if self.checkpoint_path is not None:
            self.events.subscribe(self._autosave)

    # --- the simple API ------------------------------------------------------------

    def run(self, task: str) -> str:
        """Run a task to the end and return the answer (or why it stopped)."""
        return self.agent.run(task)

    def follow_up(self, text: str) -> str:
        """Continue the finished conversation with another message."""
        self.agent.follow_up(text)
        while not self.agent.done:
            self.agent.step()
        return self.agent.state.answer

    def stream(self, task: str) -> Iterator[Event]:
        """`for event in h.stream(task)`: the run's events, tokens included, as they happen.

        Streaming is switched on for this run only, and the console printer is
        muted: whoever iterates is the one displaying the run (D178).
        """
        was_streaming, self.agent.stream = self.agent.stream, True
        self._muted = True
        try:
            yield from self.agent.iter_run(task)
        finally:
            self.agent.stream = was_streaming
            self._muted = False

    def resume(self) -> str:
        """Finish the run saved at `checkpoint=` (e.g. one stopped by the budget)."""
        saved = self.saved_run
        if saved is None:
            raise RuntimeError("Nothing to resume: no unfinished run is saved")
        self.agent.restore(saved, files=False)  # a new process: its Toolbox history is gone
        while not self.agent.done:
            self.agent.step()
        return self.agent.state.answer

    @property
    def saved_run(self) -> Checkpoint | None:
        if self.checkpoint_path is None or not self.checkpoint_path.exists():
            return None
        return Checkpoint.load(self.checkpoint_path)

    def add_helper(self, name: str, description: str, instructions: Sequence[str] = ()) -> Agent:
        """Add a read-only sub-agent the main agent can delegate to, as a tool (stage 12).

        It shares the provider (and so the budget), the event bus and the
        streaming setting, and can only see the toolbox's read-only tools.
        """
        helper = Agent(
            self.provider,
            system_prompt=default_prompt().instructions(*instructions).build(),
            tools=ToolboxView.read_only(self.toolbox),
            events=self.events,
            name=name,
            stream=self.agent.stream,
        )
        self.toolbox.add(AgentTool(name, description, helper))
        self.agent.tools = self._visible_tools()  # a read-only view is fixed when made
        return helper

    def rewind(self) -> list[ToolCommand]:
        """Undo every file change the agent made, newest first."""
        return self.toolbox.undo_all()

    @property
    def changes(self) -> list[ToolCommand]:
        """Tool calls that changed something (and haven't been undone)."""
        return [c for c in self.toolbox.history if c.tool.side_effects and not c.undone]

    # --- reporting -------------------------------------------------------------------

    @property
    def cost(self) -> float | None:
        """USD spent so far; None if any call's cost is unknown."""
        return self.stack.tracker.total.cost_usd

    def report(self) -> str:
        """One line on calls, tokens and cost, plus cache and fallback details."""
        tracker = self.stack.tracker
        total = tracker.total
        cost = "unknown" if total.cost_usd is None else f"${total.cost_usd:.6f}"
        line = f"{len(tracker.calls)} model call(s), {total.input_tokens} in / {total.output_tokens} out tokens, {cost}"
        if self.stack.cache is not None:
            line += f", cache {self.stack.cache.hits} hit(s) / {self.stack.cache.misses} miss(es)"
        if self.stack.chain is not None:
            for link, why in self.stack.chain.failures:
                line += f"\n  fell back from {link.model}: {why}"
        return line

    # --- escape hatches ----------------------------------------------------------------

    @property
    def provider(self) -> Provider:
        return self.stack.provider

    @property
    def tracker(self) -> UsageTracker:
        return self.stack.tracker

    # --- wiring ------------------------------------------------------------------------

    def _visible_tools(self) -> Toolbox | ToolboxView:
        return ToolboxView.read_only(self.toolbox) if self.read_only else self.toolbox

    def _autosave(self, event: Event) -> None:
        # Between the main agent's steps only (D117), not a helper's; a finished run
        # deletes the file so the next one starts fresh
        if event.depth > 0:
            return
        if isinstance(event, StateChanged) and not self.agent.done:
            self.agent.checkpoint().save(self.checkpoint_path)
        elif isinstance(event, RunFinished) and event.state == "done":
            self.checkpoint_path.unlink(missing_ok=True)


def _approver(approve: Approve) -> Callable[[ToolCall], bool] | None:
    if approve is True:
        return lambda call: True
    if approve is False:
        return None
    return approve
