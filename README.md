# Housestyle

Two command-line tools that check written material against an
organisation's house voice. They share one rule engine.

- `housestyle lint` reads documents and a rule set, and reports every
  place a document breaks a rule with enough precision that a person
  can fix it and a build can refuse it.
- `housestyle preview` reads a list of web pages and PDF files and
  reports what a link unfurler will show for each, checking the
  fields against the rule set and a minimum standard.

Both are deterministic. Neither calls a language model. Neither reads
anything it is not given.

## Ownership

This product is developed on the author's own account, independently,
from the behavioural specification dated 17 September 2026, from that
date. It is a clean-room build: the building session received the
specification and nothing else, and no prior implementation of this
kind of tool was read, sought or consulted.

Its first customer is a separate estate that supplies its own rule
set as data. The customer's internal documents, method material and
client records never enter this product. Rules are always the
customer's input; the product carries none of its own.

Every disagreement between this product and any tool the customer
already runs is resolved by reading the specification and deciding
which behaviour it describes, never by reading the other tool's
source.

## Versioning

Releases are numbered so that a change to the rule-set format or to
matching semantics changes the first number, and nothing else does.
Every release carries a changelog entry in plain words. No release
ships with a red self-test.

## Use

```
pip install .                      # or pin a tagged release
housestyle selftest                # must be green
housestyle lint docs --rules rules.yaml --genres genres.yaml --allow allow.yaml
housestyle preview --targets targets.txt --rules rules.yaml --standard standard.yaml
housestyle serve --port 8080 --rules rules.yaml --genres genres.yaml --allow allow.yaml
```

- [The rule-set format, genre map and allow-list](docs/rule-set.md)
- [The voice lint](docs/lint.md)
- [The share-preview checker](docs/preview.md)
- [Serve mode](docs/serve.md)
- [Changelog](CHANGELOG.md)

The customer supplies its rule set, allow-list, genre map, targets
file and minimum standard. If the customer holds its rules in another
format, the customer writes and owns the adapter; the product never
reads the customer's native format.
