# Building an Agent Harness, One Pattern at a Time

*The story of `miniharness`: what we built, what broke, what we decided, and why.*

This book retells the project from the first scaffold to the last refactor. Each chapter is one stage: the
problem that made a design pattern necessary, the options that were on the table, the choice and its
reasoning, and what real model runs taught us that tests couldn't. It's written to be **read**, start to
finish or one chapter at a time, not run.

Decisions are referenced by number (**D63**, **D136**, ...). Each one has a full entry in
[`DECISIONS.md`](../../DECISIONS.md) with every option and trade-off, if you want the long version. Your own
notes belong in [`PATTERNS.md`](../../PATTERNS.md), under each pattern's "Your notes".

## Contents

**[Preface: how this project worked](00-preface.md)**

**Part I: Foundations**
1. [The naive start: a loop and an ugly function](01-the-naive-start.md) (Template Method)
2. [Two providers, one interface](02-strategy-and-adapter.md) (Strategy and Adapter)
3. [Strings that become objects](03-factory.md) (Factory)
4. [A prompt with assembly rules](04-builder.md) (Builder)

**Part II: Doing things safely**

5. [Actions you can take back](05-command.md) (Command)
6. [Layers around every call](06-decorator.md) (Decorator)
7. [Who decides?](07-chain-of-responsibility.md) (Chain of Responsibility)
8. [Stand-ins](08-proxy.md) (Proxy)

**Part III: Control and visibility**

9. [Objects that change their own behavior](09-state.md) (State)
10. [Watching without touching](10-observer.md) (Observer)
11. [Going back in time](11-memento-and-prototype.md) (Memento and Prototype)

**Part IV: Many agents**

12. [Agents inside tools](12-composite.md) (Composite)
13. [A team that talks through a coordinator](13-mediator.md) (Mediator)
14. [Asking questions of a finished run](14-visitor.md) (Visitor)

**Part V: The shape of the whole**

15. [Answers that arrive over time](15-iterator.md) (Iterator)
16. [One front door](16-facade.md) (Facade)
17. [Two hierarchies that grow apart](17-bridge.md) (Bridge)
18. [The last global](18-singleton-to-di.md) (Singleton, and dependency injection instead)

**[Epilogue: what it all adds up to](19-epilogue.md)**

**[Appendix: cheat sheet and glossary](appendix.md)**

## How to read it

If you have an evening, read the Preface, chapters 2, 5, 6, 7 and 13, and the Epilogue. Those carry most of
the ideas. If you're reviewing one pattern, each chapter stands on its own, and ends with **the one thing to
remember** and a few **questions to think about**.

The code excerpts are short and simplified for reading. The real code lives in `src/miniharness/`, and each
chapter says where.
