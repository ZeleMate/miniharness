# Chapter 3. Strings that become objects

*Pattern: Factory. Code: `src/miniharness/providers/registry.py`.*

## The smell that stage 2 left behind

Chapter 2 removed the `if/elif` from the provider code, but a new one appeared at the edge. The example
script had to turn a command-line flag into a provider:

```python
if args.provider == "anthropic":
    provider = AnthropicProvider(model=args.model)
else:
    provider = OpenRouterProvider(model=args.model)
```

Every script that took a provider from a string would copy this, and every new provider would mean editing
all of them. This is what Factory is for: the caller asks for *what* it wants, and something else knows
*how* to build it.

## The choices

Three mechanisms were proposed. A plain dict in one file, mapping names to classes, which is obvious and
greppable. A GoF Factory Method, with each class owning a `from_config()` classmethod. Or a
**self-registering decorator**, which you chose (D12):

```python
@register_provider("openrouter")
class OpenRouterProvider: ...

provider = create_provider("openrouter:qwen/qwen3-coder")
```

Adding a provider now means writing one class. The factory never changes. That's the Open/Closed principle,
open for extension and closed for modification, in its most literal form.

The call site uses a `"provider:model"` spec string (D13), the same convention as LangChain's
`init_chat_model` and pydantic-ai. One value works on the command line, in an environment variable and in a
test. And a detail found while writing the tests: OpenRouter model ids can contain colons
(`deepseek/deepseek-chat:free`), so only the *first* colon separates provider from model (D15).

## Three things called "factory"

It's worth being precise, because the word covers three different ideas:

- A **simple factory** is one function that maps names to constructors. That's what we built, plus
  self-registration. It isn't strictly a GoF pattern.
- A **Factory Method** (GoF) is a creation method that subclasses override, such as an
  `Agent.create_provider()` hook. It varies *what gets built* through inheritance, much as Template Method
  varies steps.
- An **Abstract Factory** (GoF) builds a whole *family* of parts that must match each other: a client, an
  adapter and a pricing table that all belong to the same vendor.

## The pattern we didn't build

Abstract Factory came up and was deliberately left out (D14). Each provider had exactly one adapter, fixed
by its own constructor, so there was no family to keep consistent. The decision log recorded a trigger
instead: build it when a second per-provider component appears. Three stages later, pricing appeared,
OpenRouter reporting cost and Anthropic needing a price table, and the decision was re-examined. Still no
family that could be mismatched, so it stayed deferred, and it's still deferred at the end of the book.

That's a real outcome, not a failure. The project's rule was "no speculative patterns", and this was the
rule working.

## The costs we accepted

Self-registration is "magic at a distance". A provider only exists once its module has been imported, so
`providers/__init__.py` imports every provider module, and a test guards that all the built-ins are
registered (D16). Duplicate names raise an error rather than silently overwriting (D18), so a typo or a
double import fails loudly. And the registry was a module-level mutable dict, a global (D17). Tests that
registered a throwaway provider had to monkeypatch it to stop it leaking into other tests. That smell
was recorded and left alone. It's the subject of the very last chapter.

## A Python insight

In Python, a class is already a callable that builds objects. A dict of classes, `{"openrouter":
OpenRouterProvider}`, *is* a factory. The decorator only automates filling the dict. Several patterns in
this book shrink like this in Python, and recognizing the pattern is what lets you see the idiom for what
it is.

## The one thing to remember

**A pattern can be correctly *not* applied.** Abstract Factory had a written trigger, was checked against
it twice, and stayed out because the problem it solves never appeared.

## Questions to think about

- What would make Abstract Factory necessary here? Describe the mismatch it would prevent.
- The registry was a global. List what a test had to do because of that, before reading chapter 18.
