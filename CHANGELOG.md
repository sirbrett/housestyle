# Changelog

Releases are numbered so that a change to the rule-set format or to
matching semantics changes the first number, and nothing else does.

## 0.2.0, 18 September 2026

The interface grew, so the second number moves. The rule-set format
and matching are unchanged; a 0.1 rule set loads as it did.

- Serve mode: `housestyle serve` runs the rule engine behind a
  stateless HTTP server. POST /check takes a document id, a genre,
  text as plain text or HTML, and optional overrides keyed on a rule
  id and the exact matched text; it returns a verdict of pass, fail
  or warn and findings with a stable finding id, line and column,
  severity and remedy. GET /health reports the release and the
  loaded rule set. An optional bearer token comes from
  `HOUSESTYLE_TOKEN`. A malformed rule set refuses to start with
  exit code 2. Documented in `docs/serve.md`.
- The self-test gains a served case: start, check a known-bad
  document, check it again with an override, check the health
  route, stop.

## 0.1.2, 18 September 2026

- The share-preview checker now reads a URL target by what it serves,
  not by its extension: a body with Content-Type `application/pdf`,
  or one that carries the PDF signature, is read as a PDF and gets the
  document-properties check. Before this a PDF at a URL was read as a
  page and failed every field. A local target that is not a PDF is an
  error with a message. Tests cover a PDF served by content type at a
  URL with no extension, and one served as `application/octet-stream`
  identified by its signature alone.

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
