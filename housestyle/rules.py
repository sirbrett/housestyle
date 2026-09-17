"""Rule-set, genre-map and allow-list loading, validation and compiling.

The rule-set format belongs to this product. Customers adapt to it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

from housestyle.errors import ConfigError

FORMAT = 1
KINDS = ("word", "phrase", "spelling", "punctuation", "pattern")
SEVERITIES = ("fail", "warn")
COMMON_KEYS = {"id", "kind", "severity", "genres", "remedy", "case"}
KIND_KEYS = {
    "word": {"terms"},
    "phrase": {"terms"},
    "spelling": {"refuse", "prefer", "exceptions"},
    "punctuation": {"terms", "replacement"},
    "pattern": {"pattern"},
}
WILDCARDS = set("*?[")


@dataclass
class Rule:
    id: str
    kind: str
    severity: str
    genres: list[str]
    remedy: str
    case_exact: bool
    regex: re.Pattern
    terms: list[str] = field(default_factory=list)
    prefer: str | None = None
    replacement: str | None = None
    exceptions: list[re.Pattern] = field(default_factory=list)


@dataclass
class RuleSet:
    rules: list[Rule]
    by_id: dict[str, Rule]


@dataclass
class GenreMap:
    prefixes: list[tuple[str, str]]  # (path prefix, genre), longest first
    genres: set[str]

    def genre_for(self, relpath: str) -> str | None:
        for prefix, genre in self.prefixes:
            if relpath == prefix or relpath.startswith(prefix + "/"):
                return genre
        return None


@dataclass
class AllowEntry:
    path: str
    rules: list[str]
    why: str


@dataclass
class AllowList:
    entries: dict[str, AllowEntry]


# --- helpers ---------------------------------------------------------------

def _load_yaml(path: Path, what: str) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"{what} not found: {path}")
    except OSError as exc:
        raise ConfigError(f"{what} could not be read: {path}: {exc}")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{what} is not valid YAML: {path}: {exc}")
    if not isinstance(data, dict):
        raise ConfigError(f"{what} must be a mapping at the top level: {path}")
    return data


def _string(value, where: str, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where}: '{key}' must be a non-empty string")
    return value


def _string_list(value, where: str, key: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{where}: '{key}' must be a non-empty list")
    out = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ConfigError(f"{where}: every entry in '{key}' must be a non-empty string")
        out.append(item)
    return out


def word_forms(term: str) -> list[str]:
    """The word and its inflections: plural, possessive, past tense, gerund."""
    forms = {
        term, term + "s", term + "es", term + "ed", term + "ing",
        term + "'s", term + "s'", term + "’s", term + "s’",
    }
    if term.endswith("e"):
        forms.add(term[:-1] + "ing")
        forms.add(term + "d")
    if term.endswith("y") and len(term) > 1 and term[-2] not in "aeiou":
        forms.add(term[:-1] + "ies")
        forms.add(term[:-1] + "ied")
    return sorted(forms, key=len, reverse=True)


def _word_regex(terms: list[str], flags: int) -> re.Pattern:
    alternatives = []
    for term in terms:
        alternatives.extend(re.escape(f) for f in word_forms(term))
    alternatives.sort(key=len, reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(alternatives) + r")(?!\w)", flags)


def _phrase_regex(terms: list[str], flags: int) -> re.Pattern:
    alternatives = []
    for term in terms:
        words = term.split()
        head = r"\s+".join(re.escape(w) for w in words[:-1])
        last = re.escape(words[-1]) + r"\w*(?:['’]s)?"
        alternatives.append(head + r"\s+" + last)
    return re.compile(r"(?<!\w)(?:" + "|".join(alternatives) + r")", flags)


def _punctuation_regex(terms: list[str], flags: int) -> re.Pattern:
    alternatives = sorted((re.escape(t) for t in terms), key=len, reverse=True)
    return re.compile("|".join(alternatives), flags)


# --- rule set ----------------------------------------------------------------

def load_rules(path: Path) -> RuleSet:
    data = _load_yaml(path, "rule set")
    fmt = data.get("format")
    if fmt != FORMAT:
        raise ConfigError(
            f"rule set {path}: 'format' must be {FORMAT} for this release, got {fmt!r}"
        )
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ConfigError(f"rule set {path}: 'rules' must be a non-empty list")
    unknown_top = set(data) - {"format", "rules"}
    if unknown_top:
        raise ConfigError(f"rule set {path}: unknown top-level keys {sorted(unknown_top)}")

    rules: list[Rule] = []
    by_id: dict[str, Rule] = {}
    for index, raw in enumerate(raw_rules):
        where = f"rule set {path}: rule {index + 1}"
        if not isinstance(raw, dict):
            raise ConfigError(f"{where}: must be a mapping")
        rule_id = _string(raw.get("id"), where, "id")
        where = f"rule set {path}: rule '{rule_id}'"
        if rule_id in by_id:
            raise ConfigError(f"{where}: id is used twice")
        kind = raw.get("kind")
        if kind not in KINDS:
            raise ConfigError(f"{where}: 'kind' must be one of {list(KINDS)}, got {kind!r}")
        severity = raw.get("severity")
        if severity not in SEVERITIES:
            raise ConfigError(f"{where}: 'severity' must be 'fail' or 'warn', got {severity!r}")
        genres = _string_list(raw.get("genres"), where, "genres")
        remedy = _string(raw.get("remedy"), where, "remedy")
        case = raw.get("case", "insensitive")
        if case not in ("exact", "insensitive"):
            raise ConfigError(f"{where}: 'case' must be 'exact' or 'insensitive', got {case!r}")
        allowed = COMMON_KEYS | KIND_KEYS[kind]
        unknown = set(raw) - allowed
        if unknown:
            raise ConfigError(f"{where}: unknown keys {sorted(unknown)} for kind '{kind}'")
        flags = 0 if case == "exact" else re.IGNORECASE
        rule = _compile(kind, raw, where, flags)
        rule.id = rule_id
        rule.severity = severity
        rule.genres = genres
        rule.remedy = remedy
        rule.case_exact = case == "exact"
        rules.append(rule)
        by_id[rule_id] = rule
    return RuleSet(rules=rules, by_id=by_id)


def _compile(kind: str, raw: dict, where: str, flags: int) -> Rule:
    base = dict(id="", kind=kind, severity="", genres=[], remedy="", case_exact=False)
    if kind == "word":
        terms = _string_list(raw.get("terms"), where, "terms")
        for term in terms:
            if len(term.split()) != 1:
                raise ConfigError(f"{where}: word term {term!r} must be a single word; use kind 'phrase'")
        return Rule(regex=_word_regex(terms, flags), terms=terms, **base)
    if kind == "phrase":
        terms = _string_list(raw.get("terms"), where, "terms")
        for term in terms:
            if len(term.split()) < 2:
                raise ConfigError(f"{where}: phrase term {term!r} must be two or more words; use kind 'word'")
        return Rule(regex=_phrase_regex(terms, flags), terms=terms, **base)
    if kind == "spelling":
        refuse = _string(raw.get("refuse"), where, "refuse")
        if len(refuse.split()) != 1:
            raise ConfigError(f"{where}: 'refuse' must be a single word")
        prefer = _string(raw.get("prefer"), where, "prefer")
        raw_exceptions = raw.get("exceptions", [])
        if raw_exceptions is None:
            raw_exceptions = []
        if not isinstance(raw_exceptions, list):
            raise ConfigError(f"{where}: 'exceptions' must be a list")
        exceptions = [
            re.compile(re.escape(_string(e, where, "exceptions")), re.IGNORECASE)
            for e in raw_exceptions
        ]
        return Rule(regex=_word_regex([refuse], flags), terms=[refuse], prefer=prefer,
                    exceptions=exceptions, **base)
    if kind == "punctuation":
        terms = _string_list(raw.get("terms"), where, "terms")
        replacement = _string(raw.get("replacement"), where, "replacement")
        return Rule(regex=_punctuation_regex(terms, flags), terms=terms,
                    replacement=replacement, **base)
    if kind == "pattern":
        pattern = _string(raw.get("pattern"), where, "pattern")
        try:
            regex = re.compile(pattern, flags)
        except re.error as exc:
            raise ConfigError(f"{where}: 'pattern' is not a valid pattern: {exc}")
        return Rule(regex=regex, terms=[pattern], **base)
    raise ConfigError(f"{where}: unknown kind {kind!r}")


# --- genre map ---------------------------------------------------------------

def normalise_relpath(path: str) -> str:
    parts = [p for p in PurePosixPath(path.replace("\\", "/")).parts if p not in (".", "")]
    return "/".join(parts)


def load_genres(path: Path) -> GenreMap:
    data = _load_yaml(path, "genre map")
    raw = data.get("genres")
    if not isinstance(raw, dict) or not raw:
        raise ConfigError(f"genre map {path}: 'genres' must be a non-empty mapping of path to genre")
    prefixes = []
    genres = set()
    for raw_path, genre in raw.items():
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ConfigError(f"genre map {path}: every key must be a non-empty path")
        if not isinstance(genre, str) or not genre.strip():
            raise ConfigError(f"genre map {path}: the genre for {raw_path!r} must be a non-empty string")
        if WILDCARDS & set(raw_path):
            raise ConfigError(f"genre map {path}: {raw_path!r} contains a wildcard; use a path prefix")
        prefixes.append((normalise_relpath(raw_path), genre))
        genres.add(genre)
    prefixes.sort(key=lambda p: len(p[0]), reverse=True)
    return GenreMap(prefixes=prefixes, genres=genres)


def check_rules_against_genres(rules: RuleSet, genres: GenreMap) -> None:
    """A rule that applies to no genre in the map is a configuration error."""
    for rule in rules.rules:
        unknown = [g for g in rule.genres if g not in genres.genres]
        if unknown:
            raise ConfigError(
                f"rule '{rule.id}' applies to genre(s) {unknown} which the genre map does "
                f"not define; known genres are {sorted(genres.genres)}"
            )


# --- allow-list -------------------------------------------------------------

def load_allow(path: Path | None, rules: RuleSet, root: Path) -> AllowList:
    if path is None:
        return AllowList(entries={})
    data = _load_yaml(path, "allow-list")
    raw = data.get("allow")
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ConfigError(f"allow-list {path}: 'allow' must be a list")
    entries: dict[str, AllowEntry] = {}
    for index, item in enumerate(raw):
        where = f"allow-list {path}: entry {index + 1}"
        if not isinstance(item, dict):
            raise ConfigError(f"{where}: must be a mapping")
        unknown = set(item) - {"path", "rules", "why"}
        if unknown:
            raise ConfigError(f"{where}: unknown keys {sorted(unknown)}")
        raw_path = _string(item.get("path"), where, "path")
        if WILDCARDS & set(raw_path):
            raise ConfigError(f"{where}: path {raw_path!r} contains a wildcard; list exact file paths")
        rel = normalise_relpath(raw_path)
        if not (root / rel).is_file():
            raise ConfigError(f"{where}: path {raw_path!r} is not a file under {root}")
        if rel in entries:
            raise ConfigError(f"{where}: path {raw_path!r} is listed twice")
        ids = _string_list(item.get("rules"), where, "rules")
        for rule_id in ids:
            if rule_id not in rules.by_id:
                raise ConfigError(f"{where}: unknown rule id {rule_id!r}")
        why = _string(item.get("why"), where, "why")
        entries[rel] = AllowEntry(path=rel, rules=ids, why=why)
    return AllowList(entries=entries)
