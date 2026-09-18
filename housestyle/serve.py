"""Serve mode: the rule engine behind an HTTP server, stateless.

One rule set, genre map and allow-list are loaded at start, exactly as
the lint loads them. Nothing is written to disk and nothing is kept
between requests.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from housestyle import __version__
from housestyle.engine import find_hits
from housestyle.errors import ConfigError
from housestyle.readers import Segment, _markup_segment
from housestyle.rules import (
    FORMAT, AllowList, GenreMap, RuleSet, check_rules_against_genres, load_allow,
    load_genres, load_rules,
)

TOKEN_ENV = "HOUSESTYLE_TOKEN"
MAX_BODY = 10 * 1024 * 1024
FORMATS = ("text", "html")


class RequestError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Loaded:
    rules: RuleSet
    genres: GenreMap
    allow: AllowList
    rules_digest: str
    token: str | None


def load(rules_path: Path, genres_path: Path, allow_path: Path | None,
         root: Path | None = None, token: str | None = None) -> Loaded:
    """Load the configuration as the lint does. Raises ConfigError."""
    root = (root or Path.cwd()).resolve()
    rules = load_rules(rules_path)
    genres = load_genres(genres_path)
    check_rules_against_genres(rules, genres)
    allow = load_allow(allow_path, rules, root)
    digest = hashlib.sha256(rules_path.read_bytes()).hexdigest()
    return Loaded(rules=rules, genres=genres, allow=allow, rules_digest=digest, token=token)


def finding_id(rule_id: str, match: str) -> str:
    """Stable id from the rule id and the exact matched text."""
    return hashlib.sha256(f"{rule_id}\n{match}".encode("utf-8")).hexdigest()[:16]


def health(loaded: Loaded) -> dict:
    return {
        "release": __version__,
        "rules_format": FORMAT,
        "rules_sha256": loaded.rules_digest,
        "rules": len(loaded.rules.rules),
        "genres": sorted(loaded.genres.genres),
    }


def _require(payload: dict, key: str, kind, what: str):
    value = payload.get(key)
    if not isinstance(value, kind) or (kind is str and not value.strip() and key != "text"):
        raise RequestError(400, f"'{key}' must be {what}")
    return value


def check_document(loaded: Loaded, payload) -> dict:
    """Run the rules over one supplied document. Raises RequestError on bad input."""
    if not isinstance(payload, dict):
        raise RequestError(400, "the body must be a JSON object")
    unknown = set(payload) - {"id", "genre", "format", "text", "overrides"}
    if unknown:
        raise RequestError(400, f"unknown fields {sorted(unknown)}")
    doc_id = _require(payload, "id", str, "a non-empty string")
    genre = _require(payload, "genre", str, "a non-empty string")
    if genre not in loaded.genres.genres:
        raise RequestError(400, f"unknown genre '{genre}'; known genres are {sorted(loaded.genres.genres)}")
    fmt = _require(payload, "format", str, "'text' or 'html'")
    if fmt not in FORMATS:
        raise RequestError(400, f"'format' must be 'text' or 'html', got '{fmt}'")
    text = payload.get("text")
    if not isinstance(text, str):
        raise RequestError(400, "'text' must be a string")
    raw_overrides = payload.get("overrides", [])
    if raw_overrides is None:
        raw_overrides = []
    if not isinstance(raw_overrides, list):
        raise RequestError(400, "'overrides' must be a list")
    overrides: set[tuple[str, str]] = set()
    for index, item in enumerate(raw_overrides):
        if not isinstance(item, dict) or not isinstance(item.get("rule"), str) \
                or not isinstance(item.get("match"), str):
            raise RequestError(400, f"override {index + 1} must be an object with 'rule' and 'match' strings")
        if item["rule"] not in loaded.rules.by_id:
            raise RequestError(400, f"override {index + 1}: unknown rule id '{item['rule']}'")
        overrides.add((item["rule"], item["match"]))

    segment = _markup_segment(text) if fmt == "html" else Segment(part=None, text=text)
    exempt = set(loaded.allow.entries[doc_id].rules) if doc_id in loaded.allow.entries else set()
    applicable = [r for r in loaded.rules.rules if genre in r.genres and r.id not in exempt]

    findings = []
    fails = warns = 0
    for hit in find_hits([segment], applicable):
        overridden = (hit.rule, hit.match) in overrides
        severity = "overridden" if overridden else hit.severity
        if not overridden:
            if hit.severity == "fail":
                fails += 1
            else:
                warns += 1
        findings.append({
            "finding": finding_id(hit.rule, hit.match), "rule": hit.rule, "severity": severity,
            "match": hit.match, "line": hit.line, "col": hit.col, "remedy": hit.remedy,
        })
    verdict = "fail" if fails else ("warn" if warns else "pass")
    return {"id": doc_id, "verdict": verdict, "findings": findings}


class Handler(BaseHTTPRequestHandler):
    server_version = f"housestyle/{__version__}"
    loaded: Loaded  # set on the server class

    def log_message(self, fmt, *args):  # nothing is written anywhere
        pass

    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _authorised(self) -> bool:
        token = self.server.loaded.token
        if not token:
            return True
        header = self.headers.get("Authorization", "")
        return header == f"Bearer {token}"

    def _handle(self, method: str) -> None:
        try:
            if not self._authorised():
                raise RequestError(401, "a bearer token is required")
            if self.path == "/health":
                if method != "GET":
                    raise RequestError(405, "/health takes GET")
                self._send(200, health(self.server.loaded))
                return
            if self.path == "/check":
                if method != "POST":
                    raise RequestError(405, "/check takes POST")
                self._send(200, check_document(self.server.loaded, self._read_json()))
                return
            raise RequestError(404, f"no route {self.path}; routes are GET /health and POST /check")
        except RequestError as exc:
            self._send(exc.status, {"error": exc.message})

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise RequestError(400, "Content-Length must be a number")
        if length <= 0:
            raise RequestError(400, "a JSON body is required")
        if length > MAX_BODY:
            raise RequestError(413, f"the body may not exceed {MAX_BODY} bytes")
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RequestError(400, f"the body is not valid JSON: {exc}")

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], loaded: Loaded):
        super().__init__(address, Handler)
        self.loaded = loaded


def build_server(loaded: Loaded, host: str = "127.0.0.1", port: int = 0) -> Server:
    return Server((host, port), loaded)


def run_serve(rules_path: Path, genres_path: Path, allow_path: Path | None,
              root: Path | None, host: str, port: int) -> int:
    token = os.environ.get(TOKEN_ENV) or None
    loaded = load(rules_path, genres_path, allow_path, root, token)  # ConfigError -> exit 2
    server = build_server(loaded, host, port)
    bound = server.server_address[1]
    sys.stderr.write(
        f"housestyle {__version__} serving on http://{host}:{bound}  "
        f"({len(loaded.rules.rules)} rules, token {'required' if token else 'not set'})\n"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


__all__ = ["load", "build_server", "check_document", "health", "finding_id",
           "run_serve", "RequestError", "ConfigError", "TOKEN_ENV"]
