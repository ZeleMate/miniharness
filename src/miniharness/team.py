"""Mediator: peer agents that only ever talk through the team.

Members never hold references to each other. Each gets a `send_message`
tool that can only address the recipients its route allows (and, for
finishers, an `approve` tool). The Team delivers each message to its recipient,
runs that member's turn, and collects whatever it sends next.

Compare stage 12's Composite: there a parent *owns* and calls its children.
Here nobody owns anybody; the routing lives in one place.
"""

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from miniharness.events import MessageRouted
from miniharness.lifecycle import Done, Stopped
from miniharness.tools.toolbox import ToolSet, execute_split
from miniharness.types import ToolCall, ToolSpec

if TYPE_CHECKING:
    from miniharness.agent import Agent


@dataclass(frozen=True)
class TeamMessage:
    sender: str
    to: str
    text: str


class _MemberTools:
    """A member's own tools plus the team's coordination tools.

    The team tools are handled here, not by the member's Toolbox: they only
    queue a message for the mediator, so they skip the member's policy chain.
    """

    def __init__(self, inner: ToolSet, team: "Team", member: str):
        self.inner = inner
        self.team = team
        self.member = member

    @property
    def tools(self):
        # Coordination tools have no side effects, so only the member's own tools count
        return getattr(self.inner, "tools", {})

    def specs(self) -> dict[str, ToolSpec]:
        specs = dict(self.inner.specs())
        recipients = self.team.routes.get(self.member, [])
        if recipients:
            specs["send_message"] = {
                "description": "Send a message to a teammate. Your turn ends after you reply.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "enum": recipients},
                        "text": {"type": "string"},
                    },
                    "required": ["to", "text"],
                },
            }
        if self.member in self.team.finishers:
            specs["approve"] = {
                "description": "Approve the last message you received as the team's final result.",
                "parameters": {"type": "object", "properties": {}},
            }
        return specs

    def execute(self, call: ToolCall) -> str:
        return self.execute_all([call])[0]

    def execute_all(self, calls: list[ToolCall]) -> list[str]:
        # The member's own calls go on in batches, so they can still run together (D221)
        return execute_split(calls, self._is_team_call, self._team_call, self.inner)

    def _is_team_call(self, call: ToolCall) -> bool:
        return call.name == "send_message" or (
            call.name == "approve" and self.member in self.team.finishers
        )

    def _team_call(self, call: ToolCall) -> str:
        if call.name == "send_message":
            return self.team._send(
                self.member,
                call.arguments.get("to", ""),
                call.arguments.get("text", ""),
            )
        return self.team._approve(self.member)


class Team:
    def __init__(
        self,
        members: dict[str, "Agent"],
        routes: dict[str, list[str]],
        finishers: set[str],
        max_turns: int = 8,
    ):
        unknown = (
            {*routes} | {r for rs in routes.values() for r in rs} | finishers
        ) - set(members)
        if unknown:
            raise ValueError(
                f"Routes or finishers name unknown members: {sorted(unknown)}"
            )
        self.routes = routes
        self.finishers = finishers
        self.max_turns = max_turns
        # Our own copies: wiring in team tools must not change the caller's agents
        self.members: dict[str, Agent] = {}
        for name, agent in members.items():
            member = copy.copy(agent)
            member.name = name
            member.tools = _MemberTools(agent.tools, self, name)
            member.messages = list(
                agent.messages
            )  # a shallow copy would share the list
            self.members[name] = member
        self.log: list[TeamMessage] = []
        self._last_received: dict[str, TeamMessage] = {}
        self._outbox: list[TeamMessage] = []
        self._result: str | None = None
        self._briefed: set[str] = set()

    # --- called by members' coordination tools ------------------------------------

    def _send(self, sender: str, to: str, text: str) -> str:
        if to not in self.routes.get(sender, []):
            return f"Error: {sender} cannot send messages to {to!r}"
        self._outbox.append(TeamMessage(sender, to, text))
        return f"Message sent to {to}."

    def _approve(self, member: str) -> str:
        # The result is always a teammate's message, never text the finisher writes
        # itself: a live run showed a reviewer "approving" its own rewrite.
        received = self._last_received.get(member)
        if received is None:
            return "Error: there is nothing to approve yet"
        self._result = received.text
        return f"Approved the message from {received.sender}."

    # --- the mediation loop -------------------------------------------------------

    def run(self, first: str, task: str) -> str:
        """Deliver `task` to `first` and mediate until the team finishes.

        A team can run again: members keep their conversations (like `follow_up()`),
        while the result, the log and the brief start fresh for the new task.
        """
        self._task = task
        self.log = []
        self._last_received.clear()
        self._outbox.clear()
        self._result = None
        self._briefed.clear()
        queue = [TeamMessage("user", first, task)]
        turns = 0
        last_answer = ""
        while queue:
            message = queue.pop(0)
            turns += 1
            if turns > self.max_turns:
                return f"[stopped: max_turns] {self.max_turns} turns without finishing"
            self._deliver(message)
            member = self.members[message.to]
            while not member.done:
                member.step()
            if isinstance(member.state, Stopped):
                return (
                    member.state.answer
                )  # e.g. the shared budget ran out: stop the team
            last_answer = member.state.answer
            if self._result is not None:
                return self._result
            queue.extend(self._outbox)
            self._outbox.clear()
        return f"[stopped: no messages] {last_answer}"

    def _deliver(self, message: TeamMessage) -> None:
        self.log.append(message)
        self._last_received[message.to] = message
        member = self.members[message.to]
        member.events.emit(MessageRouted(message.sender, message.to, message.text))
        text = f"Message from {message.sender}:\n{message.text}"
        if message.to not in self._briefed and message.sender != "user":
            # A member's first turn in this run: share the team's brief, so a reviewer
            # can check the original requirements without the writer relaying them
            text = f"Team task: {self._task}\n\n{text}"
        self._briefed.add(message.to)
        if isinstance(member.state, Done):
            member.follow_up(text)
        else:
            member.start(text)
