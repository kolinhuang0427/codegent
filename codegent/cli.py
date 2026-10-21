"""Command line interface for codegent."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable

from .colors import danger, supports_color
from .tracer import GitError, GitTracer
from .tree import (
    render_ancestry,
    render_bloodline_summary,
    render_diff_lineage,
    render_genemap,
    render_trace,
)


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--rename-threshold", type=int, default=argparse.SUPPRESS, help="Rename similarity percentage, 1-100 (default: 50)")
    common.add_argument("--first-parent", action="store_true", default=argparse.SUPPRESS, help="Follow the integration branch through merges")
    common.add_argument("--no-follow", action="store_false", dest="follow", default=argparse.SUPPRESS, help="Stop at the current filename")
    common.add_argument("--author", default=argparse.SUPPRESS, help="Literal author name/email substring")
    common.add_argument("--since", default=argparse.SUPPRESS, help="Include commits since an ISO date (UTC if unspecified)")
    common.add_argument("--until", default=argparse.SUPPRESS, help="Include commits up to an ISO date")
    common.add_argument("--ref", default=argparse.SUPPRESS, help="History tip (default: HEAD)")
    common.add_argument("--repo", default=argparse.SUPPRESS, help="Git repository path")
    common.add_argument("--json", action="store_true", dest="json_output", default=argparse.SUPPRESS)
    common.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)
    common.add_argument(
        "--max-commits",
        type=positive_int,
        default=argparse.SUPPRESS,
        help="Maximum commits to inspect for history commands",
    )

    parser = argparse.ArgumentParser(
        prog="codegent",
        description="Trace the evolutionary lineage of code across git history.",
        parents=[common],
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    trace = subparsers.add_parser("trace", parents=[common], help="Trace a path's lineage")
    trace.add_argument("path", help="Path to trace")
    trace.add_argument("commit_hash", nargs="?", default=None, help="Commit/ref to trace from")
    trace.set_defaults(handler=_cmd_trace)

    ancestry = subparsers.add_parser("ancestry", parents=[common], help="Show direct ancestry")
    ancestry.add_argument("path", help="Path to trace")
    ancestry.set_defaults(handler=_cmd_ancestry)

    genemap = subparsers.add_parser("genemap", parents=[common], help="Visualize evolution")
    genemap.add_argument("path", help="Path to trace")
    genemap.set_defaults(handler=_cmd_genemap)

    bloodline = subparsers.add_parser("bloodline", parents=[common], help="Summarize lineage")
    bloodline.add_argument("path", help="Path to trace")
    bloodline.set_defaults(handler=_cmd_bloodline)

    diff = subparsers.add_parser("diff", parents=[common], help="Compare two commits")
    diff.add_argument("commit_a", help="Base commit/ref")
    diff.add_argument("commit_b", help="Target commit/ref")
    diff.set_defaults(handler=_cmd_diff)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _apply_defaults(args)
    color = supports_color(args.no_color) and not args.json_output
    handler: Callable[[argparse.Namespace, bool], Any] = args.handler
    try:
        result = handler(args, color)
    except GitError as exc:
        return _error(str(exc), json_output=args.json_output, color=color)
    except KeyboardInterrupt:
        return _error("interrupted", json_output=args.json_output, color=color)

    if args.json_output:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(result, end="" if result.endswith("\n") else "\n")
    return 0


def _apply_defaults(args: argparse.Namespace) -> None:
    defaults = {
        "ref": "HEAD", "repo": ".", "json_output": False, "no_color": False,
        "max_commits": 10000, "since": None, "until": None, "author": None, "follow": True, "first_parent": False, "rename_threshold": 50,
    }
    for key, value in defaults.items():
        if not hasattr(args, key):
            setattr(args, key, value)


def _history_options(args: argparse.Namespace) -> dict[str, Any]:
    return {"max_commits": args.max_commits, "since": args.since, "until": args.until, "author": args.author, "follow": args.follow, "first_parent": args.first_parent}


def _tracer(args: argparse.Namespace) -> GitTracer:
    return GitTracer(args.repo, rename_threshold=args.rename_threshold)


def _history(args: argparse.Namespace):
    positional_ref = getattr(args, "commit_hash", None)
    if positional_ref and args.ref != "HEAD" and positional_ref != args.ref:
        raise GitError("choose either a positional commit or --ref, not conflicting refs")
    return _tracer(args).trace_path(
        args.path, positional_ref or args.ref, **_history_options(args),
    )


def _cmd_trace(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    bloodline = _history(args)
    if args.json_output:
        return bloodline.to_dict()
    return render_trace(bloodline, color=color)


def _cmd_ancestry(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    bloodline = _history(args)
    if args.json_output:
        return bloodline.to_dict()
    return render_ancestry(bloodline, color=color)


def _cmd_genemap(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    bloodline = _history(args)
    if args.json_output:
        return bloodline.to_dict()
    return render_genemap(bloodline, color=color)


def _cmd_bloodline(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    bloodline = _history(args)
    if args.json_output:
        return bloodline.to_dict()
    return "\n" + render_bloodline_summary(bloodline, color=color) + "\n"


def _cmd_diff(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    diff = _tracer(args).diff_lineage(args.commit_a, args.commit_b)
    if args.json_output:
        return diff.to_dict()
    return render_diff_lineage(diff, color=color)


def _error(message: str, *, json_output: bool, color: bool) -> int:
    if json_output:
        print(json.dumps({"error": message}), file=sys.stderr)
    else:
        print(danger(f"codegent: {message}", color), file=sys.stderr)
    return 1
