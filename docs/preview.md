# The share-preview checker

```
housestyle preview --targets targets.txt --rules rules.yaml --standard standard.yaml
                   [--out preview-cards.html] [--format human|json] [--timeout 15]
```

The targets file has one entry per line: a URL, or a path to a PDF.
Blank lines and lines starting with `#` are ignored.

What a URL serves decides how it is read, never the URL itself: the
body is a PDF when the response's Content-Type is `application/pdf`
or the bytes carry the PDF signature, and a page otherwise. A local
target must be a PDF file; any other file is an error with a message.

For each target the checker extracts the fields a link unfurler
reads and renders one small preview card per target into the page
named by `--out`, so the result is seen rather than read. It fetches
only the target itself and the share image the target names.

## Fields

From a page:

| Field | Taken from, in order |
|-------|----------------------|
| title | `og:title`, `twitter:title`, the page `<title>` |
| description | `og:description`, `twitter:description`, `meta name=description` |
| image | `og:image`, `og:image:url`, `og:image:secure_url`, `twitter:image` |
| author | the tag named by `author_tag` in the minimum standard |
| published date | the tags named by `date_tags`, or by default `article:published_time`, `date`, `dc.date`, `dcterms.date`, `dc.date.issued`, `publish_date`, `og:published_time` |

From a PDF: title, subject (as the description), author and keywords
from the document properties, and the creation date as the
published date. A PDF has no share image.

## The minimum standard

```yaml
standard:
  genre: client-facing        # the rules that apply to this genre check the fields
  author_tag: name=author     # <meta name="author"> is the author; property=article:author also works
  image:
    min_width: 1200
    min_height: 627
  site_defaults:              # optional: strings known to be site-wide defaults
    title: ["Acme"]
    description: ["Acme is a company."]
```

## Checks, each pass or fail per target

- **title** and **description**: present and specific to the page.
  A value fails as a site-wide default when it is listed under
  `site_defaults`, when it is only the site name (`og:site_name`),
  or when another target in the same run carries the identical
  value.
- **image**: present, reachable, a PNG, JPEG, GIF or WebP, and at
  least the minimum size (1200 by 627 unless the standard says
  otherwise). Not applicable to a PDF.
- **author**: present as a display name, taken from exactly the tag
  the standard names. A display name has at least two words, does
  not start with `@`, and is not a URL.
- **date**: a published date is present.
- **clean**: every extracted text field (title, description, author,
  date, and keywords for a PDF) is clean against the rules of the
  standard's genre. Hits are listed with the rule and its remedy.
- **pdf**: a PDF carries all four properties: title, subject,
  author, keywords. Not applicable to a page.

A target that cannot be fetched or read fails every check with the
reason.

## Platforms

The checker does not emulate individual platforms. It annotates only
where they genuinely differ: one platform shows a large card only
above its minimum image size, and platforms cache a card after the
first share. The report states one truth every time a fixed target
is re-checked: a pass means the fields are now correct, and does not
change a card already cached by a platform until that platform
re-scrapes it.

## Output and exit codes

Human output is a table of targets by check, then the detail of
every failure, then the path of the cards page. JSON output
(`--format json`) carries the same fields, checks and hits.

| Code | Meaning |
|------|---------|
| 0 | every check passed on every target |
| 1 | at least one check failed |
| 2 | the configuration is wrong: a missing or empty targets file, a malformed standard or rule set, a genre no rule applies to |
