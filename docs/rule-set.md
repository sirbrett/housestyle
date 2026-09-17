# The rule-set format

A rule set is one YAML file. Customers write their rules in this
format; the product never reads any other. A change to this format,
or to what the kinds match, changes the first number of the release.

```yaml
format: 1
rules:
  - id: no-leverage
    kind: word
    severity: fail
    terms: [leverage]
    genres: [client-facing, marketing]
    remedy: Write "use" instead.
```

## Every rule carries

- `id`: a stable, unique name. Reports, allow-lists and changelogs
  refer to it.
- `kind`: one of `word`, `phrase`, `spelling`, `punctuation`,
  `pattern`.
- `severity`: `fail` refuses the build; `warn` is reported and does
  not. The `--strict` flag treats warns as fails.
- `genres`: the genres the rule applies to. Every genre named must
  exist in the genre map, and the list may not be empty. A rule that
  applies nowhere is a configuration error.
- `remedy`: one plain sentence telling the writer what to do instead.
- `case` (optional): `insensitive` is the default. `exact` matches
  the case as written, for proper nouns.

A rule with a key its kind does not use is a configuration error.

## Kinds

**word**: `terms` lists single words. Each word is matched with a
boundary on both sides, so a word inside a longer word is never a
hit ("key" never hits "keyboard" or "monkey"). Inflections count:
plural (`-s`, `-es`, `-ies`), possessive (`'s`, `s'`), past tense
(`-ed`, `-d`, `-ied`) and gerund (`-ing`, with a final `e` dropped).

**phrase**: `terms` lists phrases of two or more words. A phrase is
matched with a boundary on the left only, and any inflection of the
final word counts, so "the workshop" also hits "the workshops" and
"the workshop's". Words in a phrase may be separated by any
whitespace, including a line break.

**spelling**: `refuse` is the variant to refuse, `prefer` is the
form to use, and `exceptions` is a list of proper nouns or quoted
names inside which the variant is allowed ("Organize Inc"). The
refused variant is matched like a word, inflections included.

**punctuation**: `terms` lists characters or sequences to refuse,
matched literally with no boundaries, and `replacement` names what
the writer should use. Examples: the em dash `—`; the en dash used
as a dash, written with its spaces, `" – "`, so that a range such
as 2019–2021 is not a hit; the double hyphen `--`.

**pattern**: `pattern` describes a rhetorical shape as a regular
expression, and the pattern states its own boundaries. For example
"not X, but Y":

```yaml
pattern: '\bnot\b[^.;:!?\n]{1,80}?,\s*but\b'
```

Patterns are matched case-insensitively unless the rule sets `case:
exact`.

## The genre map

A separate YAML file mapping a path prefix to a genre. The longest
matching prefix wins. Every document must fall under some prefix; a
document with no genre is an error, not a silent pass.

```yaml
genres:
  docs: client-facing
  docs/internal: internal
  docs/method: method
```

Paths are relative to the root, which is the current folder unless
`--root` says otherwise.

## The allow-list

A separate YAML file listing exact file paths, never wildcards. Each
entry names the rule ids the file is exempt from and one sentence
saying why. A document whose job is to name a banned term is the
normal reason.

```yaml
allow:
  - path: docs/internal/banned-terms.md
    rules: [no-leverage]
    why: This document names the banned terms so that writers know them.
```

An entry naming a rule the file does not trip is reported as stale.
An entry naming an unknown rule id, a path that is not a file, or a
path with a wildcard is a configuration error.
