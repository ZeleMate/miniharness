"""Visitor: operations over a run's trace tree, kept out of the node classes.

A flat event stream (a JSONL trace, or live events) is rebuilt into a tree:

    Trace
    └ RunNode (an agent's run or turn)
      ├ ModelCallNode
      ├ ToolCallNode
      │ └ RunNode (a sub-agent started by this tool call) ...
      └ MessageNode (team messages)

Each node only knows how to `accept` a visitor. Every operation (totals,
reports, exports) is a TraceVisitor subclass, so adding one never touches
the nodes. The flip side: adding a node type touches every visitor.

    uv run python -m miniharness.trace run.jsonl --html report.html
"""

import argparse
import html
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# --- Nodes ---------------------------------------------------------------------------


@dataclass
class ModelCallNode:
    agent: str
    model: str
    stop_reason: str
    tool_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    duration_s: float

    def accept(self, visitor: "TraceVisitor") -> None:
        visitor.visit_model(self)


@dataclass
class ToolCallNode:
    agent: str
    name: str
    arguments: dict[str, Any]
    output: str
    verdict: str | None  # None: unknown tool, no policy ran
    policy: str | None
    failed: bool
    children: list["RunNode"] = field(default_factory=list)  # sub-agent runs

    def accept(self, visitor: "TraceVisitor") -> None:
        visitor.visit_tool(self)


@dataclass
class MessageNode:
    sender: str
    to: str
    text: str

    def accept(self, visitor: "TraceVisitor") -> None:
        visitor.visit_message(self)


@dataclass
class RunNode:
    agent: str
    depth: int
    task: str
    state: str = "unfinished"  # "done" / "stopped", or unfinished if the trace ends early
    answer: str = ""
    children: list[ModelCallNode | ToolCallNode | MessageNode] = field(default_factory=list)

    def accept(self, visitor: "TraceVisitor") -> None:
        visitor.visit_run(self)


@dataclass
class Trace:
    children: list[RunNode | MessageNode] = field(default_factory=list)

    def accept(self, visitor: "TraceVisitor") -> None:
        visitor.visit_trace(self)


# --- Building the tree from event records ----------------------------------------------


def build_trace(records: Iterable[dict[str, Any]]) -> Trace:
    """Rebuild the tree from event records (the JSONL tracer's format).

    Nested events arrive in post-order (DECISIONS.md D132): a sub-agent's whole
    run comes *before* the ToolCalled of the tool that started it. So a run
    that starts deeper than the open one is held as pending and attached to
    the open run's next tool call.
    """
    trace = Trace()
    open_runs: list[RunNode] = []
    pending: list[list[RunNode]] = []  # sub-runs waiting for their tool call, per open run

    for r in records:
        kind = r["event"]
        if kind == "RunStarted":
            run = RunNode(agent=r.get("agent", ""), depth=r.get("depth", 0), task=r["task"])
            if open_runs and run.depth > open_runs[-1].depth:
                pending[-1].append(run)
            else:
                trace.children.append(run)
            open_runs.append(run)
            pending.append([])
        elif kind == "ModelCalled" and open_runs:
            usage = r.get("usage") or {}
            open_runs[-1].children.append(
                ModelCallNode(
                    agent=r.get("agent", ""),
                    model=r["model"],
                    stop_reason=r["stop_reason"],
                    tool_calls=r["tool_calls"],
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    cost_usd=usage.get("cost_usd"),
                    duration_s=r["duration_s"],
                )
            )
        elif kind == "ToolCalled":
            decision = r.get("decision") or {}
            node = ToolCallNode(
                agent=r.get("agent", ""),
                name=r["call"]["name"],
                arguments=r["call"]["arguments"],
                output=r["output"],
                verdict=decision.get("verdict"),
                policy=decision.get("policy"),
                failed=r.get("failed", False),
            )
            if open_runs:
                node.children, pending[-1] = pending[-1], []
                open_runs[-1].children.append(node)
        elif kind == "MessageRouted":
            message = MessageNode(r["sender"], r["to"], r["text"])
            (open_runs[-1].children if open_runs else trace.children).append(message)
        elif kind == "RunFinished" and open_runs:
            run = open_runs.pop()
            pending.pop()
            run.state, run.answer = r["state"], r["answer"]
        # StateChanged is left out of the tree: the runs and calls already tell the story

    return trace


def load_trace(path: Path | str) -> Trace:
    with Path(path).open(encoding="utf-8") as f:
        return build_trace(json.loads(line) for line in f if line.strip())


# --- Visitors ----------------------------------------------------------------------------


class TraceVisitor:
    """Walks the whole tree by default; subclasses override what they need."""

    def visit_trace(self, node: Trace) -> None:
        for child in node.children:
            child.accept(self)

    def visit_run(self, node: RunNode) -> None:
        for child in node.children:
            child.accept(self)

    def visit_model(self, node: ModelCallNode) -> None:
        pass

    def visit_tool(self, node: ToolCallNode) -> None:
        for child in node.children:
            child.accept(self)

    def visit_message(self, node: MessageNode) -> None:
        pass


@dataclass
class AgentStats:
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = 0.0  # None once any call's cost is unknown
    tool_calls: int = 0
    denied: int = 0
    seconds: float = 0.0


class CostSummary(TraceVisitor):
    """Per-agent model calls, tokens, cost, tool calls, denials and model time."""

    def __init__(self) -> None:
        self.by_agent: dict[str, AgentStats] = {}

    def _stats(self, agent: str) -> AgentStats:
        return self.by_agent.setdefault(agent or "?", AgentStats())

    def visit_model(self, node: ModelCallNode) -> None:
        s = self._stats(node.agent)
        s.model_calls += 1
        s.input_tokens += node.input_tokens
        s.output_tokens += node.output_tokens
        s.seconds += node.duration_s
        s.cost_usd = None if s.cost_usd is None or node.cost_usd is None else s.cost_usd + node.cost_usd

    def visit_tool(self, node: ToolCallNode) -> None:
        s = self._stats(node.agent)
        s.tool_calls += 1
        if node.verdict is not None and node.verdict != "allow":
            s.denied += 1
        super().visit_tool(node)  # keep walking into sub-agent runs

    def total(self) -> AgentStats:
        t = AgentStats()
        for s in self.by_agent.values():
            t.model_calls += s.model_calls
            t.input_tokens += s.input_tokens
            t.output_tokens += s.output_tokens
            t.tool_calls += s.tool_calls
            t.denied += s.denied
            t.seconds += s.seconds
            t.cost_usd = None if t.cost_usd is None or s.cost_usd is None else t.cost_usd + s.cost_usd
        return t

    def table(self) -> str:
        rows = [*self.by_agent.items(), ("total", self.total())]
        lines = [f"{'agent':<14}{'calls':>6}{'tokens in/out':>17}{'cost':>12}{'tools':>7}{'denied':>8}{'time':>8}"]
        for name, s in rows:
            lines.append(
                f"{name:<14}{s.model_calls:>6}{f'{s.input_tokens} / {s.output_tokens}':>17}"
                f"{_money(s.cost_usd):>12}{s.tool_calls:>7}{s.denied:>8}{s.seconds:>7.1f}s"
            )
        return "\n".join(lines)


class HtmlReport(TraceVisitor):
    """A self-contained HTML page with collapsible runs. All trace text is escaped."""

    def __init__(self) -> None:
        self.parts: list[str] = []

    def visit_trace(self, node: Trace) -> None:
        summary = CostSummary()
        node.accept(summary)  # visitors compose: one visitor runs another
        self.parts.append(f"<pre class='summary'>{_e(summary.table())}</pre>")
        super().visit_trace(node)

    def visit_run(self, node: RunNode) -> None:
        cost = CostSummary()
        cost.visit_run(node)  # cost of this run, including its sub-agents
        self.parts.append(
            f"<details open class='run {_e(node.state)}'><summary><b>{_e(node.agent)}</b>: {_e(_short(node.task))}"
            f" <span class='meta'>[{_e(node.state)}] · {_money(cost.total().cost_usd)}</span></summary>"
        )
        super().visit_run(node)
        if node.answer:
            self.parts.append(f"<div class='answer'>→ {_e(node.answer)}</div>")
        self.parts.append("</details>")

    def visit_model(self, node: ModelCallNode) -> None:
        what = f"{node.tool_calls} tool call(s)" if node.tool_calls else node.stop_reason
        self.parts.append(
            f"<div class='model'>model: {_e(what)} <span class='meta'>{node.input_tokens} in / "
            f"{node.output_tokens} out · {_money(node.cost_usd)} · {node.duration_s:.1f}s</span></div>"
        )

    def visit_tool(self, node: ToolCallNode) -> None:
        cls = "tool denied" if node.verdict not in (None, "allow") else "tool failed" if node.failed else "tool"
        by = f" <span class='meta'>(by {_e(node.policy or '')})</span>" if "denied" in cls else ""
        self.parts.append(
            f"<div class='{cls}'><code>{_e(node.name)}({_e(json.dumps(node.arguments))})</code>{by}"
            f"<pre>{_e(node.output)}</pre>"
        )
        super().visit_tool(node)  # nested sub-agent runs render inside their tool call
        self.parts.append("</div>")

    def visit_message(self, node: MessageNode) -> None:
        self.parts.append(f"<div class='message'>── {_e(node.sender)} → {_e(node.to)}: {_e(node.text)}</div>")

    def page(self, title: str = "miniharness trace") -> str:
        return _PAGE.format(title=_e(title), body="\n".join(self.parts))


def _e(text: str) -> str:
    # Tool outputs and model text are untrusted: escape everything that reaches HTML
    return html.escape(str(text), quote=True)


def _money(cost: float | None) -> str:
    return "unknown" if cost is None else f"${cost:.6f}"


def _short(text: str, limit: int = 100) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ --bg:#fff; --fg:#1f2328; --muted:#656d76; --line:#d0d7de; --deny:#cf222e; --ok:#1a7f37; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#0d1117; --fg:#e6edf3; --muted:#8d96a0; --line:#30363d; --deny:#ff7b72; --ok:#3fb950; }} }}
  body {{ background:var(--bg); color:var(--fg); font:14px/1.5 system-ui, sans-serif; margin:16px; }}
  details {{ border-left:2px solid var(--line); margin:6px 0 6px 4px; padding-left:12px; }}
  summary {{ cursor:pointer; }}
  .meta {{ color:var(--muted); font-size:12px; }}
  .model, .tool, .message, .answer {{ margin:4px 0; }}
  .tool pre {{ margin:2px 0 0; white-space:pre-wrap; color:var(--muted); max-height:12em; overflow:auto; }}
  .denied code, .failed code {{ color:var(--deny); }}
  .answer {{ color:var(--ok); }}
  .summary {{ border:1px solid var(--line); padding:8px; overflow-x:auto; }}
</style></head>
<body><h1>{title}</h1>
{body}
</body></html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize a JSONL trace, optionally as HTML.")
    parser.add_argument("trace", help="a JSONL file written by JsonlTracer (--trace)")
    parser.add_argument("--html", help="write an HTML report here")
    args = parser.parse_args()

    trace = load_trace(args.trace)
    summary = CostSummary()
    trace.accept(summary)
    print(summary.table())
    if args.html:
        report = HtmlReport()
        trace.accept(report)
        Path(args.html).write_text(report.page(f"Trace: {Path(args.trace).name}"), encoding="utf-8")
        print(f"\nWrote {args.html}")


if __name__ == "__main__":
    main()
