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
    for skipped in actual["skipped"]:
        out(f"  UNEXPECTED skipped  {skipped}")
        problems.append(f"unexpected skipped file: {skipped}")

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

    if problems:
        out(f"SELF-TEST RED: {len(problems)} expectation(s) moved")
        for p in problems:
            out(f"  - {p}")
        return 1
    out(f"SELF-TEST GREEN: {len(act_hits)} hits, {len(actual['stale'])} stale entry, exit codes as expected")
    return 0
