"""Command-line entry points: housestyle lint, housestyle preview, housestyle selftest."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from housestyle import __version__
from housestyle.errors import ConfigError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="housestyle",
        description="Check written material against an organisation's house voice.",
    )
    parser.add_argument("--version", action="version", version=f"housestyle {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    lint = sub.add_parser("lint", help="report every place a document breaks a rule")
    lint.add_argument("paths", nargs="+", help="files or folders; folders are read recursively")
    lint.add_argument("--rules", required=True, type=Path, help="the rule set (YAML)")
    lint.add_argument("--genres", required=True, type=Path, help="the genre map (YAML)")
    lint.add_argument("--allow", type=Path, default=None, help="the allow-list (YAML)")
    lint.add_argument("--root", type=Path, default=None,
                      help="paths are reported relative to this folder (default: current folder)")
    lint.add_argument("--format", choices=("human", "json"), default="human")
    lint.add_argument("--strict", action="store_true", help="treat warns as fails")

    preview = sub.add_parser("preview", help="report what a link unfurler will show for each target")
    preview.add_argument("--targets", required=True, type=Path,
                         help="one URL or PDF path per line")
    preview.add_argument("--rules", required=True, type=Path, help="the rule set (YAML)")
    preview.add_argument("--standard", required=True, type=Path,
                         help="the minimum standard (YAML)")
    preview.add_argument("--out", type=Path, default=Path("preview-cards.html"),
                         help="where to write the page of cards")
    preview.add_argument("--format", choices=("human", "json"), default="human")
    preview.add_argument("--timeout", type=float, default=15.0, help="seconds per fetch")

    serve = sub.add_parser("serve", help="check documents over HTTP, statelessly")
    serve.add_argument("--port", required=True, type=int, help="port to listen on")
    serve.add_argument("--host", default="127.0.0.1", help="address to bind (default 127.0.0.1)")
    serve.add_argument("--rules", required=True, type=Path, help="the rule set (YAML)")
    serve.add_argument("--genres", required=True, type=Path, help="the genre map (YAML)")
    serve.add_argument("--allow", type=Path, default=None, help="the allow-list (YAML)")
    serve.add_argument("--root", type=Path, default=None,
                       help="allow-list paths resolve against this folder (default: current folder)")

    sub.add_parser("selftest", help="run the lint self-test against the shipped fixtures")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "lint":
            from housestyle.lint import run_lint
            report = run_lint(
                paths=args.paths, rules_path=args.rules, genres_path=args.genres,
                allow_path=args.allow, root=args.root, strict=args.strict,
            )
            sys.stdout.write(report.to_json() if args.format == "json" else report.to_human())
            return report.exit_code
        if args.command == "preview":
            from housestyle.preview import run_preview
            report = run_preview(
                targets_path=args.targets, rules_path=args.rules,
                standard_path=args.standard, out_path=args.out, timeout=args.timeout,
            )
            sys.stdout.write(report.to_json() if args.format == "json" else report.to_human())
            return report.exit_code
        if args.command == "serve":
            from housestyle.serve import run_serve
            return run_serve(rules_path=args.rules, genres_path=args.genres, allow_path=args.allow,
                             root=args.root, host=args.host, port=args.port)
        if args.command == "selftest":
            from housestyle.selftest.runner import run
            return run()
    except ConfigError as exc:
        sys.stderr.write(f"housestyle: configuration error: {exc}\n")
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
