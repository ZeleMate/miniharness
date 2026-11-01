# Chapter 3. Strings that become objects

*Pattern: [Factory](https://refactoring.guru/design-patterns/factory-comparison). Code: `src/miniharness/providers/registry.py`.*

## The smell stage 2 leaves behind

Chapter 2 removes the `if/elif` from the provider code, but a new one appears at the edge. The example
script has to turn a command-line flag into a provider:

```python
if args.provider == "anthropic":
    provider = AnthropicProvider(model=args.model)
else:
    provider = OpenRouterProvider(model=args.model)
```

Every script that takes a provider from a string would copy this, and every new provider would mean
editing all of them. This is what Factory is for: the caller asks for *what* it wants, and something else
knows *how* to build it.

## The choices

There are three mechanisms. A plain dict in one file, mapping names to classes, which is obvious and
greppable. A GoF Factory Method, with each class owning a `from_config()` classmethod. Or a
**self-registering decorator**, which is what the code uses (D12):

```python
@register_provider("openrouter")
class OpenRouterProvider: ...


provider = create_provider("openrouter:qwen/qwen3-coder")
```

Adding a provider means writing one class. The factory never changes. That's the Open/Closed principle,
open for extension and closed for modification, in its most literal form.

The call site uses a `"provider:model"` spec string (D13), the same convention as LangChain's
`init_chat_model` and pydantic-ai. One value works on the command line, in an environment variable and in a
test. One detail: OpenRouter model ids can contain colons (`deepseek/deepseek-chat:free`), so only the
*first* colon separates provider from model (D15).

## Three things called "factory"

The word covers three different ideas:

- A **simple factory** is one function that maps names to constructors. That's what this registry is,
  plus self-registration. It isn't strictly a GoF pattern.
- A **Factory Method** (GoF) is a creation method that subclasses override, such as an
  `Agent.create_provider()` hook. It varies *what gets built* through inheritance, much as Template Method
  varies steps.
- An **Abstract Factory** (GoF) builds a whole *family* of parts that must match each other: a client, an
  adapter and a pricing table that all belong to the same vendor.

## The pattern that isn't built

Abstract Factory is deliberately left out (D14). Each provider has exactly one adapter, fixed by its own
constructor, so there's no family to keep consistent. Instead of the pattern, the design rationale records
a trigger: build it when a second per-provider component appears. In chapter 6, pricing appears
(OpenRouter reports cost, Anthropic needs a price table), and the decision is re-examined. There's still no
family that could be mismatched, so it stays deferred to the end of the book.

That's a correct outcome. "No speculative patterns" means a pattern with a written trigger that never
fires stays out.

## The costs

Self-registration is "magic at a distance". A provider only exists once its module has been imported, so
`providers/__init__.py` imports every provider module, and a test guards that all the built-ins are
registered (D16). Duplicate names raise an error rather than silently overwriting (D18), so a typo or a
double import fails loudly. And the registry is a module-level mutable dict, a global (D17). Tests that
register a throwaway provider have to monkeypatch it to stop it leaking into other tests. That smell is
left in place on purpose; it's the subject of chapter 18.

## A Python insight

In Python, a class is already a callable that builds objects. A dict of classes, `{"openrouter":
OpenRouterProvider}`, *is* a factory. The decorator only automates filling the dict. Several patterns in
this book shrink like this in Python, and recognizing the pattern is what lets you see the idiom for what it
is.

## The one thing to remember

**A pattern can be correctly *not* applied.** Abstract Factory has a written trigger, is checked against it
twice, and stays out because the problem it solves never appears.

## Questions to think about

- What would make Abstract Factory necessary here? Describe the mismatch it would prevent.
- The registry is a global. List what a test has to do because of that, before reading chapter 18.
