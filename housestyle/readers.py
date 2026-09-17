"""Readers that turn a document into text segments with exact positions.

Markdown and plain text are read as they are. HTML and SVG are read as
their text nodes only: never markup, attributes, style or script. PDF is
read by its text layer, one segment per page, and by its document
properties, one segment each.
"""
from __future__ import annotations

import html
from bisect import bisect_right
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from housestyle.errors import ReadError

TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".text"}
MARKUP_SUFFIXES = {".html", ".htm", ".xhtml", ".svg"}
PDF_SUFFIXES = {".pdf"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | MARKUP_SUFFIXES | PDF_SUFFIXES

PDF_PROPERTIES = (("title", "/Title"), ("subject", "/Subject"),
                  ("author", "/Author"), ("keywords", "/Keywords"))

# Tags whose text runs on from the surrounding text. Every other tag
# separates text nodes, so that "foo</li><li>bar" is never "foobar".
INLINE_TAGS = {
    "a", "abbr", "b", "bdi", "bdo", "cite", "code", "data", "del", "dfn",
    "em", "i", "ins", "kbd", "mark", "q", "s", "samp", "small", "span",
    "strong", "sub", "sup", "time", "u", "var", "tspan",
}
SKIPPED_TAGS = {"script", "style"}


@dataclass
class Segment:
    """A run of document text with anchors that map offsets to positions."""

    part: str | None
    text: str
    anchors: list[tuple[int, int, int]] = field(default_factory=lambda: [(0, 1, 1)])

    def locate(self, offset: int) -> tuple[int, int]:
        """Line and column (both 1-based) of the character at offset."""
        starts = [a[0] for a in self.anchors]
        index = bisect_right(starts, offset) - 1
        a_off, line, col = self.anchors[index]
        chunk = self.text[a_off:offset]
        newlines = chunk.count("\n")
        if newlines:
            line += newlines
            col = offset - (a_off + chunk.rfind("\n"))
        else:
            col += offset - a_off
        return line, col


def supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_SUFFIXES


def read_segments(path: Path) -> list[Segment]:
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return [Segment(part=None, text=_read_utf8(path))]
    if suffix in MARKUP_SUFFIXES:
        return [_markup_segment(_read_utf8(path))]
    if suffix in PDF_SUFFIXES:
        return _pdf_segments(path)
    raise ReadError(f"{path}: unsupported format '{suffix or 'no extension'}'")


def _read_utf8(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ReadError(f"{path}: {exc.strerror or exc}")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ReadError(f"{path}: not valid UTF-8 at byte {exc.start}")


class _TextNodes(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.anchors: list[tuple[int, int, int]] = []
        self.length = 0
        self.skip_depth = 0

    def _add(self, text: str) -> None:
        if not text:
            return
        line, offset = self.getpos()
        self.anchors.append((self.length, line, offset + 1))
        self.parts.append(text)
        self.length += len(text)

    def _separate(self) -> None:
        self._add("\n")

    def handle_starttag(self, tag, attrs):
        if tag in SKIPPED_TAGS:
            self.skip_depth += 1
        if tag not in INLINE_TAGS:
            self._separate()

    def handle_endtag(self, tag):
        if tag in SKIPPED_TAGS and self.skip_depth:
            self.skip_depth -= 1
        if tag not in INLINE_TAGS:
            self._separate()

    def handle_startendtag(self, tag, attrs):
        if tag not in INLINE_TAGS:
            self._separate()

    def handle_data(self, data):
        if not self.skip_depth:
            self._add(data)

    def handle_entityref(self, name):
        if not self.skip_depth:
            self._add(html.unescape(f"&{name};"))

    def handle_charref(self, name):
        if self.skip_depth:
            return
        try:
            code = int(name[1:], 16) if name[:1] in "xX" else int(name)
            self._add(chr(code))
        except (ValueError, OverflowError):
            self._add(f"&#{name};")


def _markup_segment(source: str) -> Segment:
    parser = _TextNodes()
    parser.feed(source)
    parser.close()
    text = "".join(parser.parts)
    anchors = parser.anchors or [(0, 1, 1)]
    return Segment(part=None, text=text, anchors=anchors)


def _pdf_segments(path: Path) -> list[Segment]:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as exc:  # pragma: no cover
        raise ReadError(f"{path}: the pypdf package is needed to read PDF files: {exc}")
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise ReadError(f"{path}: the PDF is encrypted and cannot be read")
        segments: list[Segment] = []
        for number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                segments.append(Segment(part=f"page {number}", text=text))
        metadata = reader.metadata or {}
        for name, key in PDF_PROPERTIES:
            value = metadata.get(key)
            if value is not None and str(value).strip():
                segments.append(Segment(part=f"property {name}", text=str(value)))
        return segments
    except ReadError:
        raise
    except (PdfReadError, OSError, ValueError, KeyError, TypeError) as exc:
        raise ReadError(f"{path}: could not read PDF: {exc}")


def pdf_properties(path: Path) -> dict[str, str | None]:
    """The four document properties of a PDF, missing ones as None."""
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError as exc:  # pragma: no cover
        raise ReadError(f"{path}: the pypdf package is needed to read PDF files: {exc}")
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise ReadError(f"{path}: the PDF is encrypted and cannot be read")
        metadata = reader.metadata or {}
    except ReadError:
        raise
    except (PdfReadError, OSError, ValueError, KeyError, TypeError) as exc:
        raise ReadError(f"{path}: could not read PDF: {exc}")
    out: dict[str, str | None] = {}
    for name, key in PDF_PROPERTIES:
        value = metadata.get(key)
        out[name] = str(value).strip() if value is not None and str(value).strip() else None
    return out
