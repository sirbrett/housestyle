# Serve mode

```
HOUSESTYLE_TOKEN=... housestyle serve --port 8080 --rules rules.yaml --genres genres.yaml [--allow allow.yaml] [--host 127.0.0.1] [--root .]
```

The server loads one rule set, one genre map and one allow-list at
start, exactly as the lint does. A malformed rule set, a rule that
applies to no genre, or an allow-list naming an unknown rule refuses
to start with a message and exit code 2.

It is stateless: nothing is written to disk and nothing is remembered
between requests. Every response is JSON. Errors are JSON with an
`error` message and a 4xx status.

## Token

When the environment variable `HOUSESTYLE_TOKEN` is set, every
request must carry `Authorization: Bearer <token>` or gets 401. When
it is not set, no token is checked. There is no other configuration.

## POST /check

Request:

```json
{
  "id": "docs/pricing.md",
  "genre": "client-facing",
  "format": "text",
  "text": "We leverage the workshops.",
  "overrides": [{"rule": "no-leverage", "match": "leverage"}]
}
```

- `id`: any string the caller chooses. A document whose id equals a
  path in the allow-list is exempt from that entry's rules.
- `genre`: a genre the genre map defines. The rules that apply to it
  are run. An unknown genre is a 400.
- `format`: `text` or `html`. HTML is read as text nodes only, as the
  lint reads it: never markup, attributes, style or script blocks.
  Line and column are positions within the supplied text either way.
- `overrides`: optional. Each names a rule id and the exact matched
  text, and means the caller has ruled that hit allowed for this
  document. The match is exact, including case. An unknown rule id
  is a 400.

Response:

```json
{
  "id": "docs/pricing.md",
  "verdict": "warn",
  "findings": [
    {"finding": "91fb46ace8233714", "rule": "no-leverage", "severity": "overridden",
     "match": "leverage", "line": 1, "col": 4, "remedy": "Write \"use\" instead."},
    {"finding": "09aedf535508793e", "rule": "no-the-workshop", "severity": "warn",
     "match": "the workshops", "line": 1, "col": 13, "remedy": "Call it the session."}
  ]
}
```

- `verdict` is `fail` when any finding not overridden has severity
  fail; otherwise `warn` when any finding not overridden has severity
  warn; otherwise `pass`. Warns never make the verdict fail.
- `finding` is a stable id derived from the rule id and the exact
  matched text: the first 16 hex characters of SHA-256 over the rule
  id, a newline, and the match. The same rule and match give the
  same id in every request and every release, so a caller can key an
  override on it.
- A finding that matches an override is returned with severity
  `overridden` and counts toward nothing.

The body may not exceed 10 MB.

## GET /health

```json
{"release": "0.2.0", "rules_format": 1, "rules_sha256": "83b0...", "rules": 9,
 "genres": ["client-facing", "internal", "method"]}
```

`rules_format` is the rule-set format number the release reads.
`rules_sha256` identifies the rule-set file that is loaded, so a
caller can tell which rules are live without the server remembering
anything.

## Self-test

`housestyle selftest` includes a served case: start, check a known-bad
document and match its findings to the lint's, check it again with
every fail overridden, check the health route, stop.
