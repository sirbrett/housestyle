"""The voice lint: documents in, precise hits out, exit code for a build."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from housestyle.engine import Hit, find_hits
from housestyle.errors import ConfigError, ReadError
from housestyle.readers import read_segments, supported
from housestyle.rules import (
    check_rules_against_genres, load_allow, load_genres, load_rules, normalise_relpath,
)

EXIT_CLEAN = 0
EXIT_FAIL = 1
EXIT_CONFIG = 2


@dataclass
class FileHit:
    path: str
    hit: Hit

    def as_dict(self) -> dict:
        return {
            "path": self.path, "part": self.hit.part, "line": self.hit.line,
            "col": self.hit.col, "rule": self.hit.rule, "severity": self.hit.severity,
            "match": self.hit.match, "remedy": self.hit.remedy,
        }


@dataclass
class Report:
    hits: list[FileHit] = field(default_factory=list)
    stale: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    files: int = 0
    strict: bool = False

    @property
    def fails(self) -> int:
        return sum(1 for h in self.hits if h.hit.severity == "fail")

    @property
    def warns(self) -> int:
        return sum(1 for h in self.hits if h.hit.severity == "warn")

    @property
    def exit_code(self) -> int:
        if self.errors:
            return EXIT_CONFIG
        if self.fails or (self.strict and self.warns):
            return EXIT_FAIL
        return EXIT_CLEAN

    def as_dict(self) -> dict:
        return {
            "hits": [h.as_dict() for h in self.hits],
            "stale": list(self.stale),
            "skipped": list(self.skipped),
            "errors": list(self.errors),
            "files": self.files,
            "fails": self.fails,
            "warns": self.warns,
            "exit": self.exit_code,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, ensure_ascii=False) + "\n"

    def to_human(self) -> str:
        lines = []
        for fh in self.hits:
            h = fh.hit
            where = f"{fh.path}:{h.line}:{h.col}"
            if h.part:
                where += f" ({h.part})"
            lines.append(f'{where}  {h.severity}  {h.rule}  "{h.match}"  {h.remedy}')
        for s in self.stale:
            lines.append(
                f"{s['path']}  stale  the allow-list exempts {s['rule']} but the file does not trip it"
            )
        for s in self.skipped:
            lines.append(f"{s['path']}  skipped  {s['reason']}")
        for e in self.errors:
            lines.append(f"error  {e}")
        noun = "file" if self.files == 1 else "files"
        summary = f"{self.files} {noun} checked, {self.fails} fail, {self.warns} warn"
        if self.strict and self.warns:
            summary += " (strict: warns count as fails)"
        if self.errors:
            summary += f", {len(self.errors)} error"
        lines.append(summary)
        return "\n".join(lines) + "\n"


def collect_files(paths: list[str], root: Path) -> tuple[list[tuple[Path, str]], list[dict], list[str]]:
    """Resolve the given paths to (absolute path, path relative to root)."""
    files: list[tuple[Path, str]] = []
    skipped: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()

    def add(path: Path, explicit: bool) -> None:
        try:
            rel = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            errors.append(f"{path} is outside the root {root}")
            return
        if rel in seen:
            return
        if not supported(path):
            if explicit:
                errors.append(f"{rel}: unsupported format '{path.suffix or 'no extension'}'")
            else:
                skipped.append({"path": rel, "reason": f"unsupported format '{path.suffix or 'no extension'}'"})
            return
        seen.add(rel)
        files.append((path, rel))

    for given in paths:
        path = Path(given)
        if path.is_file():
            add(path, explicit=True)
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if any(part.startswith(".") for part in child.relative_to(path).parts):
                    continue
                if child.is_file():
                    add(child, explicit=False)
        else:
            errors.append(f"unknown path: {given}")
    files.sort(key=lambda item: item[1])
    return files, skipped, errors


def run_lint(paths: list[str], rules_path: Path, genres_path: Path,
             allow_path: Path | None, root: Path | None = None,
             strict: bool = False) -> Report:
    """Lint the paths. Raises ConfigError when the configuration is wrong."""
    root = (root or Path.cwd()).resolve()
    rules = load_rules(rules_path)
    genres = load_genres(genres_path)
    check_rules_against_genres(rules, genres)
    allow = load_allow(allow_path, rules, root)

    report = Report(strict=strict)
    files, report.skipped, report.errors = collect_files(paths, root)
    if report.errors:
        return report

    tripped_allowed: dict[str, set[str]] = {}
    for path, rel in files:
        genre = genres.genre_for(rel)
        if genre is None:
            report.errors.append(f"{rel}: no genre in the genre map covers this path")
            continue
        try:
            segments = read_segments(path)
        except ReadError as exc:
            report.errors.append(str(exc))
            continue
        report.files += 1
        applicable = [r for r in rules.rules if genre in r.genres]
        exempt = set(allow.entries[rel].rules) if rel in allow.entries else set()
        for hit in find_hits(segments, applicable):
            if hit.rule in exempt:
                tripped_allowed.setdefault(rel, set()).add(hit.rule)
                continue
            report.hits.append(FileHit(path=rel, hit=hit))

    linted = {rel for _, rel in files}
    for rel, entry in allow.entries.items():
        if rel not in linted:
            continue
        for rule_id in entry.rules:
            if rule_id not in tripped_allowed.get(rel, set()):
                report.stale.append({"path": rel, "rule": rule_id, "why": entry.why})

    report.hits.sort(key=lambda fh: (fh.path, fh.hit.sort_key()))
    report.stale.sort(key=lambda s: (s["path"], s["rule"]))
    return report


def resolve_relpath(given: str, root: Path) -> str:
    return normalise_relpath(str(Path(given).resolve().relative_to(root.resolve())))


__all__ = ["run_lint", "Report", "FileHit", "ConfigError", "EXIT_CLEAN", "EXIT_FAIL", "EXIT_CONFIG"]
