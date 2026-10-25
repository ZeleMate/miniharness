"""Bridge: agent types (the abstraction) × providers (the implementation).

`Agent` holds a `Provider` and never asks which one it is. That alone was
stage 2's Strategy. It becomes a Bridge once the *agent* side is a hierarchy
of its own that grows independently. The classes here are refined
abstractions: each reshapes the loop through the Template Method hooks
(`first_state`, `after_answer`) and reaches the model only through the
provider. So 3 agent types and any number of providers (wrappers included)
need 3 + N classes, not 3 × N:

    PlannerAgent(create_provider("openrouter")).run(task)
    ReviewerAgent(MockProvider(script)).run(task)
    Harness("anthropic", agent_type=PlannerAgent).run(task)
"""

from miniharness.agent import Agent
from miniharness.lifecycle import AgentState, Planning, Thinking
from miniharness.types import LLMResponse, Message

PLAN_REQUEST = (
    "Before doing anything, write a short numbered plan (at most 5 steps) for the task above. "
    "Don't call any tools and don't carry out the plan yet. Tools you can use later:\n{tools}"
)
EXECUTE_REQUEST = "Now carry out the plan, step by step. Use tools where they help."
REVIEW_REQUEST = (
    "Review your answer above against the original request. Check it for mistakes, gaps and "
    "claims you didn't verify; use tools to check if that helps. Then reply with only the final "
    "answer, corrected if needed, exactly as the user should see it."
)


class PlannerAgent(Agent):
    """Plan first, then act: one tool-less call for a plan, then the normal tool loop.

    The plan stays in the conversation, so every later step can see it.
    Planning happens on `start()` only; a `follow_up()` continues without a new plan.
    """

    execute_request = EXECUTE_REQUEST

    def first_state(self) -> AgentState:
        return Planning()

    def plan_request(self) -> str:
        """The planning call gets no tools (D194), so the request names them instead."""
        specs = self.tools.specs()
        tools = (
            "\n".join(
                f"- {name}: {spec['description']}" for name, spec in specs.items()
            )
            or "(none)"
        )
        return PLAN_REQUEST.format(tools=tools)


class ReviewerAgent(Agent):
    """Draft, review, finish: the first answer of each turn is reviewed once before it's final.

    The review is another round of the normal loop, with tools, so a fix can
    be checked. Whether this turn was reviewed already is read from the
    conversation, which keeps checkpoints and forks right without extra state.
    """

    review_request = REVIEW_REQUEST

    def after_answer(self, response: LLMResponse) -> AgentState:
        # Only a complete answer is worth reviewing; a refusal or a cut-off reply finishes as before
        if response.stop_reason != "end" or self._reviewed_this_turn():
            return super().after_answer(response)
        self.messages.append(Message(role="user", content=self.review_request))
        return Thinking()

    def _reviewed_this_turn(self) -> bool:
        last_user = next((m for m in reversed(self.messages) if m.role == "user"), None)
        return last_user is not None and last_user.content == self.review_request
