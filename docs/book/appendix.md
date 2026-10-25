# Appendix: cheat sheet and glossary

## Which pattern when

| You notice... | Reach for | Not to be confused with |
|---|---|---|
| the same algorithm, with steps that vary per subclass | **Template Method** (ch. 1) | Strategy: composition instead of inheritance |
| interchangeable implementations picked by the caller | **Strategy** (ch. 2) | State: the object changes itself |
| an interface that doesn't fit the one you need | **Adapter** (ch. 2) | Bridge: designed up front |
| `if kind == ...: X() elif ...` scattered around | **Factory** (ch. 3) | Abstract Factory: families of matching parts |
| construction with ordering or validation rules | **Builder** + Director (ch. 4) | a long constructor: just use keyword arguments |
| actions you need to log, queue, replay or undo | **Command** (ch. 5) | a plain callback |
| the same extra behavior around many implementations | **Decorator** (ch. 6) | Proxy: controls access instead |
| several rules where the first that applies decides | **Chain of Responsibility** (ch. 7) | Decorator: every layer runs |
| expensive creation, access control or remote work | **Proxy** (ch. 8) | Decorator: adds behavior instead |
| behavior that depends on history (`if self.mode == ...`) | **State** (ch. 9) | Strategy: the caller chooses |
| "let anyone react when X happens" | **Observer** (ch. 10) | Mediator: routes with knowledge of everyone |
| save, restore, rewind | **Memento** (ch. 11) | serialization alone, with no restore semantics |
| copy a configured object, keeping its type | **Prototype** (ch. 11) | calling a constructor |
| a group that should behave like a single item | **Composite** (ch. 12) | a plain list of children |
| peers wired to each other in a tangle | **Mediator** (ch. 13) | Facade: one-way, for outside clients |
| many operations over a stable set of node types | **Visitor** (ch. 14) | methods on the nodes, if node types keep growing |
| results that arrive over time; caller-paced processing | **Iterator** (ch. 15) | Observer: push instead of pull |
| a subsystem too complex for its common use | **Facade** (ch. 16) | Mediator: sits between peers |
| two hierarchies that both grow | **Bridge** (ch. 17) | Strategy: only one hierarchy |
| a global "the one X" that tests must reset | **dependency injection** (ch. 18) | a ContextVar: per-execution facts |

## Glossary

**Abstraction / implementor (Bridge).** The two sides a Bridge joins. Here: agent types and providers.

**Characterization test.** A test that pins down what code currently *does*, so a refactor can't change it
by accident. It describes, rather than judges.

**Compensating command.** Undoing an action by running its inverse (refund instead of "un-charge"), used when
the old state can't be snapshotted. The basis of the Saga pattern.

**ContextVar.** A Python variable with a separate value per thread and per asyncio task, set and reset by
code as execution moves. Used here to know which agent is running.

**Defense in depth.** Several independent safeguards, so one failing doesn't expose everything. Here: a view
hides tools, and the policy chain checks what's left.

**Dependency injection.** Giving an object what it needs (a registry, a provider, a bus) instead of letting it
reach for a global. "Whoever creates an object wires it."

**Director.** The companion to a Builder that knows a standard recipe. In Python, usually a function:
`default_prompt()`, `build_stack()`.

**Double dispatch.** Choosing code based on two types at once, the node's and the visitor's. The mechanism
behind Visitor.

**Expression problem.** The trade-off between making new *operations* cheap (Visitor) and making new
*types* cheap (methods on the types). You can't easily have both.

**Fail closed.** When unsure, refuse. The opposite, fail open, allows by default.

**Information hiding.** Not revealing what exists. Hidden tools return the same error as missing ones.

**Interface segregation.** Depend on the smallest interface you actually use. The Agent needs two methods
from its tools, so it asks for a two-method protocol.

**Least privilege.** Grant only the access needed. The default toolbox can't touch the disk.

**Open/Closed principle.** Code should be open for extension and closed for modification. Self-registering
providers extend the factory without editing it.

**Optimistic concurrency.** Assume nobody else changed something, but check before acting, and refuse if they
did. Undo refuses when a file changed after our write.

**Post-order.** Children reported before their parent. Nested agent events arrive this way.

**Protocol (typing).** Structural typing in Python: anything with the right methods qualifies, with no
inheritance needed.

**Pull vs push.** Iterator (the consumer asks for the next item) vs Observer (the producer delivers items when
it wants).

**State-local data.** Data owned by a state object, so entering the state resets it automatically.

**Transient error.** A failure that might succeed if retried or sent elsewhere (timeouts, rate limits, server
errors), as opposed to a configuration error (a bad key, an unknown model), which never will.
