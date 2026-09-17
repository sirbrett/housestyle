"""The share-preview checker: what a link unfurler will show, checked."""
from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

import yaml

from housestyle.engine import check_text
from housestyle.errors import ConfigError, ReadError
from housestyle.imagesize import image_size
from housestyle.readers import pdf_properties
from housestyle.rules import Rule, load_rules

CHECKS = ("title", "description", "image", "author", "date", "clean", "pdf")
FIELDS = ("title", "description", "image", "author", "date")
USER_AGENT = "housestyle-preview/0.1"
MAX_IMAGE_BYTES = 20 * 1024 * 1024

CACHE_NOTE = (
    "A pass means the fields are now correct. It does not change a card a "
    "platform has already cached from an earlier share; that card updates "
    "only when the platform re-scrapes the page."
)
IMAGE_NOTE = (
    "One platform shows a large card only when the image is at least {w} by "
    "{h}; below that it shows a small thumbnail or none."
)

DEFAULT_DATE_TAGS = [
    ("property", "article:published_time"),
    ("name", "article:published_time"),
    ("name", "date"),
    ("name", "dc.date"),
    ("name", "dcterms.date"),
    ("name", "dc.date.issued"),
    ("name", "publish_date"),
    ("property", "og:published_time"),
]


@dataclass
class Standard:
    genre: str
    author_tag: tuple[str, str]
    date_tags: list[tuple[str, str]]
    min_width: int
    min_height: int
    default_titles: list[str]
    default_descriptions: list[str]


@dataclass
class Check:
    status: str  # pass, fail, n/a
    detail: str = ""

    def as_dict(self) -> dict:
        return {"status": self.status, "detail": self.detail}


@dataclass
class Target:
    target: str
    kind: str  # page or pdf
    fields: dict[str, str | None] = field(default_factory=dict)
    site_name: str | None = None
    image_info: str = ""
    checks: dict[str, Check] = field(default_factory=dict)
    hits: list[dict] = field(default_factory=list)
    error: str | None = None

    @property
    def passed(self) -> bool:
        return all(c.status != "fail" for c in self.checks.values())

    def as_dict(self) -> dict:
        return {
            "target": self.target, "kind": self.kind, "fields": dict(self.fields),
            "checks": {k: v.as_dict() for k, v in self.checks.items()},
            "hits": list(self.hits), "error": self.error, "result": "pass" if self.passed else "fail",
        }


@dataclass
class PreviewReport:
    targets: list[Target]
    standard: Standard
    out_path: Path

    @property
    def failed(self) -> int:
        return sum(1 for t in self.targets if not t.passed)

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0

    def as_dict(self) -> dict:
        return {
            "targets": [t.as_dict() for t in self.targets],
            "checked": len(self.targets), "failed": self.failed,
            "cards": str(self.out_path), "note": CACHE_NOTE, "exit": self.exit_code,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, ensure_ascii=False) + "\n"

    def to_human(self) -> str:
        width = max([len("target")] + [min(len(t.target), 60) for t in self.targets])
        head = f"{'target':<{width}}  " + "  ".join(f"{c:<11}" for c in CHECKS) + "  result"
        lines = [head, "-" * len(head)]
        for t in self.targets:
            name = t.target if len(t.target) <= 60 else t.target[:57] + "..."
            cells = "  ".join(f"{t.checks[c].status:<11}" for c in CHECKS)
            lines.append(f"{name:<{width}}  {cells}  {'PASS' if t.passed else 'FAIL'}")
        lines.append("")
        for t in self.targets:
            details = [(c, t.checks[c]) for c in CHECKS if t.checks[c].status == "fail"]
            if details or t.error:
                lines.append(t.target)
                if t.error:
                    lines.append(f"  error: {t.error}")
                    continue
                for name, check in details:
                    lines.append(f"  {name}: {check.detail}")
        lines.append(f"{len(self.targets)} target(s) checked, {self.failed} failed; cards written to {self.out_path}")
        lines.append(CACHE_NOTE)
        return "\n".join(lines) + "\n"


# --- configuration -------------------------------------------------------

def _parse_tag(value, where: str) -> tuple[str, str]:
    if not isinstance(value, str) or "=" not in value:
        raise ConfigError(f"{where}: must be written as attribute=value, for example name=author")
    attr, _, val = value.partition("=")
    attr, val = attr.strip().lower(), val.strip()
    if attr not in ("name", "property", "itemprop") or not val:
        raise ConfigError(f"{where}: the attribute must be name, property or itemprop, with a value")
    return attr, val


def load_standard(path: Path) -> Standard:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"minimum standard not found: {path}")
    except yaml.YAMLError as exc:
        raise ConfigError(f"minimum standard is not valid YAML: {path}: {exc}")
    if not isinstance(data, dict) or not isinstance(data.get("standard"), dict):
        raise ConfigError(f"minimum standard {path}: must have a top-level 'standard' mapping")
    std = data["standard"]
    unknown = set(std) - {"genre", "author_tag", "date_tags", "image", "site_defaults"}
    if unknown:
        raise ConfigError(f"minimum standard {path}: unknown keys {sorted(unknown)}")
    genre = std.get("genre")
    if not isinstance(genre, str) or not genre.strip():
        raise ConfigError(f"minimum standard {path}: 'genre' must name the genre whose rules apply to the fields")
    author_tag = _parse_tag(std.get("author_tag"), f"minimum standard {path}: 'author_tag'")
    raw_dates = std.get("date_tags")
    if raw_dates is None:
        date_tags = list(DEFAULT_DATE_TAGS)
    elif isinstance(raw_dates, list) and raw_dates:
        date_tags = [_parse_tag(d, f"minimum standard {path}: 'date_tags'") for d in raw_dates]
    else:
        raise ConfigError(f"minimum standard {path}: 'date_tags' must be a non-empty list")
    image = std.get("image") or {}
    if not isinstance(image, dict):
        raise ConfigError(f"minimum standard {path}: 'image' must be a mapping")
    min_w = image.get("min_width", 1200)
    min_h = image.get("min_height", 627)
    if not isinstance(min_w, int) or not isinstance(min_h, int) or min_w < 1 or min_h < 1:
        raise ConfigError(f"minimum standard {path}: image min_width and min_height must be positive integers")
    defaults = std.get("site_defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError(f"minimum standard {path}: 'site_defaults' must be a mapping")

    def strings(key):
        val = defaults.get(key) or []
        if not isinstance(val, list) or not all(isinstance(v, str) for v in val):
            raise ConfigError(f"minimum standard {path}: site_defaults.{key} must be a list of strings")
        return [v.strip() for v in val]

    return Standard(
        genre=genre.strip(), author_tag=author_tag, date_tags=date_tags,
        min_width=min_w, min_height=min_h,
        default_titles=strings("title"), default_descriptions=strings("description"),
    )


def load_targets(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"targets file not found: {path}")
    except UnicodeDecodeError:
        raise ConfigError(f"targets file is not valid UTF-8: {path}")
    targets = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            targets.append(line)
    if not targets:
        raise ConfigError(f"targets file has no targets: {path}")
    return targets


# --- extraction ----------------------------------------------------------

class _Meta(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: list[tuple[str, str, str]] = []  # (attr, key, content)
        self.title: str | None = None
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "meta":
            a = {k.lower(): (v or "") for k, v in attrs}
            content = a.get("content")
            if content is None:
                return
            for attr in ("property", "name", "itemprop"):
                if attr in a:
                    self.meta.append((attr, a[attr].strip().lower(), content.strip()))
        elif tag == "title" and self.title is None:
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title" and self._in_title:
            self._in_title = False
            self.title = " ".join("".join(self._title_parts).split())

    def handle_data(self, data):
        if self._in_title:
            self._title_parts.append(data)

    def first(self, *keys: tuple[str, str]) -> str | None:
        for attr, key in keys:
            for m_attr, m_key, content in self.meta:
                if m_attr == attr and m_key == key.lower() and content:
                    return content
        return None


def _fetch(url: str, timeout: float, limit: int | None = None) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content_type = resp.headers.get("Content-Type", "")
        data = resp.read(limit) if limit else resp.read()
    return data, content_type


def _decode(data: bytes, content_type: str) -> str:
    m = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    encodings = [m.group(1)] if m else []
    head = data[:4096].decode("ascii", "ignore")
    m = re.search(r'<meta[^>]+charset=["\']?([\w-]+)', head, re.I)
    if m:
        encodings.append(m.group(1))
    encodings.append("utf-8")
    for enc in encodings:
        try:
            return data.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", "replace")


def extract_page(target: Target, source: str, standard: Standard) -> None:
    parser = _Meta()
    parser.feed(source)
    parser.close()
    f = target.fields
    f["title"] = parser.first(("property", "og:title"), ("name", "twitter:title")) or parser.title
    f["description"] = parser.first(
        ("property", "og:description"), ("name", "twitter:description"), ("name", "description"))
    image = parser.first(
        ("property", "og:image"), ("property", "og:image:url"),
        ("property", "og:image:secure_url"), ("name", "twitter:image"))
    f["image"] = urllib.parse.urljoin(target.target, image) if image else None
    f["author"] = parser.first(standard.author_tag)
    f["date"] = parser.first(*standard.date_tags)
    target.site_name = parser.first(("property", "og:site_name"))


def extract_pdf(target: Target, path: Path) -> None:
    props = pdf_properties(path)
    target.fields.update({
        "title": props["title"], "description": props["subject"], "image": None,
        "author": props["author"], "date": None, "keywords": props["keywords"],
    })
    try:
        from pypdf import PdfReader
        meta = PdfReader(str(path)).metadata or {}
        raw = meta.get("/CreationDate") or meta.get("/ModDate")
        target.fields["date"] = str(raw) if raw else None
    except Exception:  # noqa: BLE001 - properties already read; date is best effort
        target.fields["date"] = None


# --- checks --------------------------------------------------------------

def _is_display_name(value: str) -> tuple[bool, str]:
    v = value.strip()
    if v.startswith("@"):
        return False, f'"{v}" starts with @, which is an account name'
    if "://" in v or v.startswith("www."):
        return False, f'"{v}" is a URL, not a display name'
    if len(v.split()) < 2:
        return False, f'"{v}" is one word; a display name has at least two, as in a first and last name'
    return True, f'"{v}"'


def _specific(name: str, value: str | None, target: Target, standard: Standard,
              shared: dict[str, set[str]]) -> Check:
    if not value:
        return Check("fail", f"no {name} found")
    defaults = standard.default_titles if name == "title" else standard.default_descriptions
    if value.strip() in defaults:
        return Check("fail", f'"{value}" is a listed site-wide default')
    if target.site_name and value.strip().lower() == target.site_name.strip().lower():
        return Check("fail", f'"{value}" is only the site name')
    if value.strip() in shared[name]:
        return Check("fail", f'"{value}" is shared with another target in this run, so it is a site-wide default')
    return Check("pass", f'"{value}"')


def _check_image(target: Target, standard: Standard, timeout: float) -> Check:
    if target.kind == "pdf":
        return Check("n/a", "a PDF has no share image")
    url = target.fields.get("image")
    if not url:
        return Check("fail", "no share image tag found")
    try:
        data, _ = _fetch(url, timeout, limit=MAX_IMAGE_BYTES)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        return Check("fail", f"image {url} is not reachable: {exc}")
    size = image_size(data)
    if not size:
        return Check("fail", f"image {url} is not a PNG, JPEG, GIF or WebP image")
    fmt, w, h = size
    target.image_info = f"{fmt} {w} by {h}"
    if w < standard.min_width or h < standard.min_height:
        return Check("fail", f"image is {w} by {h}, below the minimum of "
                             f"{standard.min_width} by {standard.min_height}")
    return Check("pass", f"{fmt} {w} by {h}, reachable")


def run_checks(target: Target, standard: Standard, rules: list[Rule],
               shared: dict[str, set[str]], timeout: float) -> None:
    c = target.checks
    c["title"] = _specific("title", target.fields.get("title"), target, standard, shared)
    c["description"] = _specific("description", target.fields.get("description"), target, standard, shared)
    c["image"] = _check_image(target, standard, timeout)
    author = target.fields.get("author")
    if not author:
        attr, key = standard.author_tag
        c["author"] = Check("fail", f"no author: expected <meta {attr}=\"{key}\"> on a page"
                            if target.kind == "page" else "no author: the PDF Author property is empty")
    else:
        ok, detail = _is_display_name(author)
        c["author"] = Check("pass" if ok else "fail", detail)
    date = target.fields.get("date")
    c["date"] = Check("pass", f'"{date}"') if date else Check("fail", "no published date found")

    hits = []
    for name in ("title", "description", "author", "date", "keywords"):
        value = target.fields.get(name)
        if not value:
            continue
        for h in check_text(value, rules, part=name):
            hits.append({"field": name, "col": h.col, "rule": h.rule, "severity": h.severity,
                         "match": h.match, "remedy": h.remedy})
    target.hits = hits
    if hits:
        c["clean"] = Check("fail", "; ".join(f'{h["field"]}: {h["rule"]} "{h["match"]}", {h["remedy"]}' for h in hits))
    else:
        c["clean"] = Check("pass", "every field is clean against the rule set")

    if target.kind == "pdf":
        missing = [k for k in ("title", "subject", "author", "keywords")
                   if not target.fields.get("description" if k == "subject" else k)]
        c["pdf"] = Check("fail", f"missing propert{'y' if len(missing) == 1 else 'ies'}: {', '.join(missing)}") \
            if missing else Check("pass", "title, subject, author and keywords all present")
    else:
        c["pdf"] = Check("n/a", "not a PDF")


def _fail_all(target: Target, reason: str) -> None:
    target.error = reason
    for name in CHECKS:
        target.checks[name] = Check("fail", reason)


# --- driver --------------------------------------------------------------

def run_preview(targets_path: Path, rules_path: Path, standard_path: Path,
                out_path: Path, timeout: float = 15.0) -> PreviewReport:
    rules = load_rules(rules_path)
    standard = load_standard(standard_path)
    applicable = [r for r in rules.rules if standard.genre in r.genres]
    if not applicable:
        raise ConfigError(f"no rule in {rules_path} applies to genre '{standard.genre}' named by the minimum standard")
    targets = [Target(target=t, kind="page" if "://" in t else "pdf") for t in load_targets(targets_path)]

    for t in targets:
        try:
            if t.kind == "pdf":
                path = Path(t.target)
                if not path.is_file():
                    raise ReadError(f"{t.target}: not a file")
                extract_pdf(t, path)
            else:
                data, content_type = _fetch(t.target, timeout)
                extract_page(t, _decode(data, content_type), standard)
        except ReadError as exc:
            _fail_all(t, str(exc))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            _fail_all(t, f"not reachable: {exc}")

    shared: dict[str, set[str]] = {"title": set(), "description": set()}
    for name in shared:
        seen: dict[str, int] = {}
        for t in targets:
            v = (t.fields.get(name) or "").strip()
            if v:
                seen[v] = seen.get(v, 0) + 1
        shared[name] = {v for v, n in seen.items() if n > 1}

    for t in targets:
        if t.error is None:
            run_checks(t, standard, applicable, shared, timeout)

    report = PreviewReport(targets=targets, standard=standard, out_path=out_path)
    out_path.write_text(render_cards(report), encoding="utf-8")
    return report


# --- cards ---------------------------------------------------------------

def render_cards(report: PreviewReport) -> str:
    std = report.standard
    e = html.escape
    cards = []
    for t in report.targets:
        f = t.fields
        image = f.get("image")
        if t.kind == "pdf":
            figure = '<div class="img none">PDF: no share image</div>'
        elif image and t.checks.get("image", Check("fail")).status == "pass":
            figure = f'<img src="{e(image)}" alt="">'
        elif image:
            figure = f'<div class="img none">image fails: {e(t.checks["image"].detail)}</div>'
        else:
            figure = '<div class="img none">no image</div>'
        host = urllib.parse.urlsplit(t.target).netloc if t.kind == "page" else "PDF"
        rows = "".join(
            f'<li class="{t.checks[c].status.replace("/", "")}"><b>{c}</b> '
            f'<span>{t.checks[c].status}</span> <small>{e(t.checks[c].detail)}</small></li>'
            for c in CHECKS
        )
        cards.append(f"""
<section class="card {'pass' if t.passed else 'fail'}">
  <div class="preview">
    {figure}
    <div class="text">
      <div class="host">{e(host)}</div>
      <div class="title">{e(f.get('title') or '(no title)')}</div>
      <div class="desc">{e(f.get('description') or '(no description)')}</div>
      <div class="by">{e(f.get('author') or '(no author)')} · {e(f.get('date') or '(no date)')}</div>
    </div>
  </div>
  <div class="target"><a href="{e(t.target)}">{e(t.target)}</a> <strong>{'PASS' if t.passed else 'FAIL'}</strong></div>
  <ul class="checks">{rows}</ul>
</section>""")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Share previews</title>
<style>
  :root {{ --bg: #f6f6f4; --fg: #1a1a1a; --card: #fff; --line: #d8d8d4; --pass: #1f7a3a; --fail: #b3261e; --na: #777; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg: #141414; --fg: #eee; --card: #1e1e1e; --line: #333; --pass: #5bd48a; --fail: #ff7b72; --na: #999; }} }}
  body {{ margin: 0; padding: 16px; background: var(--bg); color: var(--fg); font: 15px/1.45 system-ui, sans-serif; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  p.note {{ max-width: 70ch; margin: 0 0 20px; color: var(--na); }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }}
  .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }}
  .card.fail {{ border-color: var(--fail); }}
  .preview img, .preview .img {{ display: block; width: 100%; aspect-ratio: 1.91; object-fit: cover; background: #ccc; }}
  .preview .img.none {{ display: flex; align-items: center; justify-content: center; color: #333; font-size: 13px; padding: 8px; box-sizing: border-box; text-align: center; }}
  .preview .text {{ padding: 10px 12px; border-bottom: 1px solid var(--line); }}
  .host {{ font-size: 12px; text-transform: uppercase; color: var(--na); }}
  .title {{ font-weight: 600; margin: 2px 0; }}
  .desc {{ font-size: 14px; color: var(--na); }}
  .by {{ font-size: 12px; margin-top: 6px; }}
  .target {{ padding: 8px 12px; font-size: 13px; word-break: break-all; display: flex; justify-content: space-between; gap: 8px; }}
  .checks {{ list-style: none; margin: 0; padding: 4px 12px 10px; font-size: 13px; }}
  .checks li {{ display: grid; grid-template-columns: 90px 44px 1fr; gap: 6px; padding: 2px 0; }}
  .checks li span {{ font-weight: 600; }}
  .checks li.pass span {{ color: var(--pass); }}
  .checks li.fail span {{ color: var(--fail); }}
  .checks li.na span {{ color: var(--na); }}
  .checks small {{ color: var(--na); overflow-wrap: anywhere; }}
</style>
</head>
<body>
<h1>Share previews: {len(report.targets)} target(s), {report.failed} failed</h1>
<p class="note">{e(CACHE_NOTE)} {e(IMAGE_NOTE.format(w=std.min_width, h=std.min_height))}</p>
<div class="grid">{''.join(cards)}
</div>
</body>
</html>
"""
