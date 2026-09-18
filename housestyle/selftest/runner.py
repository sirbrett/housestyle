"""The lint self-test: fixtures with known hits that must not move."""
from __future__ import annotations

import json
from pathlib import Path

from housestyle.errors import ConfigError
from housestyle.lint import run_lint
from housestyle.rules import check_rules_against_genres, load_genres, load_rules

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
EXPECTED = HERE / "expected.json"


def _describe(hit: dict) -> str:
    where = f"{hit['path']}:{hit['line']}:{hit['col']}"
    if hit.get("part"):
        where += f" ({hit['part']})"
    return f'{where}  {hit["severity"]}  {hit["rule"]}  "{hit["match"]}"  {hit["remedy"]}'


def run(out=print) -> int:
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    report = run_lint(
        paths=[str(FIXTURES / "docs")],
        rules_path=FIXTURES / "rules.yaml",
        genres_path=FIXTURES / "genres.yaml",
        allow_path=FIXTURES / "allow.yaml",
        root=FIXTURES,
    )
    actual = report.as_dict()
    problems: list[str] = []

    out(f"self-test: {report.files} fixture files under {FIXTURES}")
    exp_hits = expected["hits"]
    act_hits = actual["hits"]
    exp_keys = [json.dumps(h, sort_keys=True) for h in exp_hits]
    act_keys = [json.dumps(h, sort_keys=True) for h in act_hits]
    for key, hit in zip(exp_keys, exp_hits):
        mark = "ok " if key in act_keys else "MISSING "
        out(f"  {mark}{_describe(hit)}")
        if key not in act_keys:
            problems.append(f"expected hit missing: {_describe(hit)}")
    for key, hit in zip(act_keys, act_hits):
        if key not in exp_keys:
            out(f"  UNEXPECTED {_describe(hit)}")
            problems.append(f"unexpected hit: {_describe(hit)}")
    if exp_keys == act_keys:
        out(f"  ok  {len(act_hits)} hits in the expected order")
    elif not problems:
        problems.append("hits are the expected set but in a different order")

    for stale in expected["stale"]:
        present = stale in actual["stale"]
        out(f"  {'ok ' if present else 'MISSING '}{stale['path']}  stale  {stale['rule']}")
        if not present:
            problems.append(f"expected stale entry missing: {stale}")
    for stale in actual["stale"]:
        if stale not in expected["stale"]:
            out(f"  UNEXPECTED {stale['path']}  stale  {stale['rule']}")
            problems.append(f"unexpected stale entry: {stale}")

    for err in actual["errors"]:
        out(f"  UNEXPECTED error  {err}")
        problems.append(f"unexpected error: {err}")
    if actual["skipped"]["count"]:
        out(f"  UNEXPECTED skipped  {actual['skipped']}")
        problems.append(f"unexpected skipped files under docs: {actual['skipped']}")

    out(f"  {'ok ' if actual['exit'] == expected['exit'] else 'WRONG '}exit code {actual['exit']} (expected {expected['exit']})")
    if actual["exit"] != expected["exit"]:
        problems.append(f"exit code {actual['exit']}, expected {expected['exit']}")

    def exit_for(rel: str, strict: bool) -> int:
        return run_lint(
            paths=[str(FIXTURES / rel)], rules_path=FIXTURES / "rules.yaml",
            genres_path=FIXTURES / "genres.yaml", allow_path=None, root=FIXTURES,
            strict=strict,
        ).exit_code

    # strict/warn-only.md trips one warn and nothing else.
    codes = (exit_for("strict/warn-only.md", False), exit_for("strict/warn-only.md", True),
             exit_for("docs/good.md", True))
    ok = codes == (0, 1, 0)
    out(f"  {'ok ' if ok else 'WRONG '}strict flag: warn-only file exits {codes[0]} plain, "
        f"{codes[1]} strict; clean file exits {codes[2]} strict")
    if not ok:
        problems.append(f"strict flag exit codes were {codes}, expected (0, 1, 0)")

    # skip/ holds one document and three unsupported files. The walk may skip
    # them, but must report the count and the extensions, never silently.
    walk = run_lint(paths=[str(FIXTURES / "skip")], rules_path=FIXTURES / "rules.yaml",
                    genres_path=FIXTURES / "genres.yaml", allow_path=None, root=FIXTURES)
    want = {"count": 3, "extensions": {"(none)": 1, ".jpg": 1, ".png": 1}}
    got = walk.as_dict()["skipped"]
    human = walk.to_human()
    ok = got == want and walk.files == 1 and walk.exit_code == 0 and \
        "skipped 3 unsupported files found by folder walk: (none) (1), .jpg (1), .png (1)" in human
    out(f"  {'ok ' if ok else 'WRONG '}folder walk reports skipped files: {got}")
    if not ok:
        problems.append(f"folder walk skip report was {got}, expected {want}; human output: {human!r}")

    try:
        rules = load_rules(FIXTURES / "rules.yaml")
        genres = load_genres(FIXTURES / "genres-missing.yaml")
        check_rules_against_genres(rules, genres)
        out("  WRONG a rule applying to an unknown genre was accepted")
        problems.append("a rule applying to an unknown genre was accepted")
    except ConfigError as exc:
        out(f"  ok  unknown genre refused: {exc}")

    unknown = run_lint(paths=[str(FIXTURES / "docs" / "missing.md")],
                       rules_path=FIXTURES / "rules.yaml", genres_path=FIXTURES / "genres.yaml",
                       allow_path=None, root=FIXTURES)
    out(f"  {'ok ' if unknown.exit_code == 2 else 'WRONG '}unknown path exits 2: {unknown.errors[0] if unknown.errors else 'no error'}")
    if unknown.exit_code != 2:
        problems.append("an unknown path did not exit 2")

    problems.extend(_served_case(out))

    if problems:
        out(f"SELF-TEST RED: {len(problems)} expectation(s) moved")
        for p in problems:
            out(f"  - {p}")
        return 1
    out(f"SELF-TEST GREEN: {len(act_hits)} hits, {len(actual['stale'])} stale entry, exit codes as expected")
    return 0


def _served_case(out) -> list[str]:
    """Start the server, check a known-bad document, check it again with an
    override, check the health route, stop."""
    import json
    import threading
    import urllib.request

    from housestyle import __version__
    from housestyle.serve import build_server, finding_id, load

    problems: list[str] = []
    loaded = load(FIXTURES / "rules.yaml", FIXTURES / "genres.yaml", FIXTURES / "allow.yaml",
                  root=FIXTURES)
    server = build_server(loaded, "127.0.0.1", 0)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def call(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())

    try:
        bad = (FIXTURES / "docs" / "bad.md").read_text(encoding="utf-8")
        doc = {"id": "bad.md", "genre": "client-facing", "format": "text", "text": bad}

        status, first = call("POST", "/check", doc)
        # The same hits as the lint finds in docs/bad.md, in the same order.
        expected = [(h["rule"], h["match"], h["line"], h["col"])
                    for h in json.loads(EXPECTED.read_text())["hits"] if h["path"] == "docs/bad.md"]
        got = [(f["rule"], f["match"], f["line"], f["col"]) for f in first["findings"]]
        ok = status == 200 and first["verdict"] == "fail" and got == expected
        out(f"  {'ok ' if ok else 'WRONG '}served: bad document gives verdict {first.get('verdict')} "
            f"with {len(first.get('findings', []))} findings matching the lint")
        if not ok:
            problems.append(f"served check of bad.md: status {status}, verdict {first.get('verdict')}, findings {got}")

        fails = [f for f in first["findings"] if f["severity"] == "fail"]
        overrides = [{"rule": f["rule"], "match": f["match"]} for f in fails]
        status, second = call("POST", "/check", {**doc, "overrides": overrides})
        overridden = [f for f in second["findings"] if f["severity"] == "overridden"]
        ids_stable = all(f["finding"] == finding_id(f["rule"], f["match"]) for f in second["findings"])
        same_ids = [f["finding"] for f in first["findings"]] == [f["finding"] for f in second["findings"]]
        ok = (status == 200 and second["verdict"] == "warn" and len(overridden) == len(fails)
              and ids_stable and same_ids)
        out(f"  {'ok ' if ok else 'WRONG '}served: with every fail overridden the verdict is "
            f"{second.get('verdict')}, {len(overridden)} findings marked overridden, ids stable")
        if not ok:
            problems.append(f"served override check: verdict {second.get('verdict')}, overridden {len(overridden)} of {len(fails)}")

        status, h = call("GET", "/health")
        ok = status == 200 and h.get("release") == __version__ and h.get("rules_format") == 1 \
            and len(h.get("rules_sha256", "")) == 64
        out(f"  {'ok ' if ok else 'WRONG '}served: /health reports release {h.get('release')}, "
            f"rule-set format {h.get('rules_format')}")
        if not ok:
            problems.append(f"served health: {status} {h}")
    finally:
        server.shutdown()
        server.server_close()
    out("  ok  served: stopped")
    return problems
