# Changelog

Releases are numbered so that a change to the rule-set format or to
matching semantics changes the first number, and nothing else does.

## 0.1.1, 17 September 2026

- The voice lint now reports what a folder walk skipped: the count of
  unsupported files and how many per extension, in both output forms,
  with each skipped path listed in the JSON form. A skip is never
  silent. The self-test checks this.

## 0.1.0, 17 September 2026

The first release, built clean-room from the behavioural
specification of the same date.

- The rule-set format, version 1: word, phrase, spelling,
  punctuation and pattern rules, each with a stable id, a severity,
  the genres it applies to and a remedy sentence. A genre map keyed
  by path prefix. An allow-list of exact file paths with reasons.
- The voice lint. Reads Markdown, plain text, HTML and SVG text
  nodes, and PDF text and document properties. Reports every hit
  with path, line, column, rule, severity, matched text and remedy,
  in human or JSON form. Exit code 0 for clean, 1 for a fail, 2 for
  a wrong configuration; a strict flag treats warns as fails. Stale
  allow-list entries are reported.
- The self-test, run with `housestyle selftest`, over fixtures with
  known hits: a clean document, a bad one with every hit listed, a
  word inside a longer word, a phrase with an inflected last word, a
  banned term inside a stylesheet, a term on an allow-listed file.
- The share-preview checker. Extracts title, description, image,
  author and published date from pages and PDFs, checks them against
  a minimum standard and the rule set, renders one card per target
  as a page, and exits non-zero when any check fails.

Not in this release, deliberately: document formats beyond those
listed, and suggested fixes in place of remedies in words.
