# The voice lint

```
housestyle lint PATH... --rules rules.yaml --genres genres.yaml [--allow allow.yaml]
                        [--root .] [--format human|json] [--strict]
```

Paths may be files or folders. Folders are read recursively; entries
whose names start with a dot are not documents and are not read. A
folder walk may skip files whose format is not supported, but never
silently: the report gives the count skipped and how many per
extension, and the JSON form lists each skipped path as well. A file
named on the command line whose format is not supported is an
error.

## Formats read

- Markdown and plain text (`.md`, `.markdown`, `.txt`, `.text`) as
  they are.
- HTML and SVG (`.html`, `.htm`, `.xhtml`, `.svg`) as their text
  nodes only. Markup, attributes, `<style>` and `<script>` blocks are
  never checked, so a property name in a stylesheet is never a
  spelling hit. Text either side of an inline tag such as `<em>` is
  one run of text, so a phrase split by emphasis is still found.
- PDF (`.pdf`) by its text layer, and by its document properties
  (title, subject, author, keywords), which are checked as text.
  Hits carry a part: `page 3`, or `property title`.

Every file must be readable: one that is not valid UTF-8, an
encrypted PDF, a path that does not exist, or a path no genre
covers, is an error with a message and exit code 2.

## The report

Every hit gives the file path, line and column (1-based), the rule
id, the severity, the exact matched text and the remedy. Hits are
ordered by file, then by position.

Human form, one hit per line:

```
docs/bad.md:3:4  fail  no-leverage  "leverage"  Write "use" instead.
docs/report.pdf:1:1 (property title)  fail  no-key  "Key"  Say what makes it important instead of calling it key.
docs/internal/banned-terms.md  stale  the allow-list exempts no-key but the file does not trip it
skipped 3 unsupported files found by folder walk: (none) (1), .jpg (1), .png (1)
2 files checked, 2 fail, 0 warn
```

Machine form (`--format json`) carries the same hits:

```json
{
  "hits": [
    {"path": "docs/bad.md", "part": null, "line": 3, "col": 4,
     "rule": "no-leverage", "severity": "fail", "match": "leverage",
     "remedy": "Write \"use\" instead."}
  ],
  "stale": [{"path": "docs/internal/banned-terms.md", "rule": "no-key", "why": "..."}],
  "skipped": {"count": 3, "extensions": {"(none)": 1, ".jpg": 1, ".png": 1}},
  "skipped_files": [{"path": "docs/logo.png", "extension": ".png"}],
  "errors": [],
  "files": 2, "fails": 2, "warns": 0, "exit": 1
}
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | no fails (warns may be present) |
| 1 | at least one fail, or with `--strict` at least one warn |
| 2 | the configuration is wrong: a malformed rule set, a rule applying to no genre, an unknown path, an unreadable file, an unknown rule id in the allow-list |

## The self-test

```
housestyle selftest
```

Runs the lint over the fixtures shipped inside the package and
compares every hit with the expected list. It prints each expected
hit as it is matched, and fails loudly with a list of everything
that moved. No release ships with a red self-test.
