"""Command line interface for codegent."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
from functools import partial
import sys
from typing import Any, Callable

from .colors import danger, supports_color
from .exports import render_markdown
from .display import escape_text
from ._version import __version__
from .tracer import GitError, GitTracer
from .reports import author_report, render_authors, hotspot_report, render_hotspots, render_owners
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


class ReportArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, json_errors: bool = False, **kwargs):
        self.json_errors = json_errors
        super().__init__(*args, **kwargs)

    def error(self, message: str) -> None:
        if self.json_errors:
            self.exit(2, json.dumps({"error": message}) + "\n")
        super().error(message)


def build_parser(*, json_errors: bool = False) -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--version", action="version", version=f"codegent {__version__}")
    common.add_argument("--output", default=argparse.SUPPRESS, help="Atomically write a report to a file; - means stdout")
    common.add_argument("--mailmap", action="store_true", default=argparse.SUPPRESS, help="Canonicalize history authors with .mailmap")
    common.add_argument("--ignore-whitespace", action="store_true", default=argparse.SUPPRESS, help="Ignore whitespace in textual change statistics")
    common.add_argument("--timeout", type=float, default=argparse.SUPPRESS, help="Timeout in seconds for each Git process (default: 30)")
    common.add_argument("--rename-threshold", type=int, default=argparse.SUPPRESS, help="Rename similarity percentage, 1-100 (default: 50)")
    common.add_argument("--first-parent", action="store_true", default=argparse.SUPPRESS, help="Follow the integration branch through merges")
    common.add_argument("--no-follow", action="store_false", dest="follow", default=argparse.SUPPRESS, help="Stop at the current filename")
    common.add_argument("--author", default=argparse.SUPPRESS, help="Literal author name/email substring")
    common.add_argument("--since", default=argparse.SUPPRESS, help="Include commits since an ISO date (UTC if unspecified)")
    common.add_argument("--until", default=argparse.SUPPRESS, help="Include commits up to an ISO date")
    common.add_argument("--ref", default=argparse.SUPPRESS, help="History tip (default: HEAD)")
    common.add_argument("--repo", default=argparse.SUPPRESS, help="Git repository path")
    formats = common.add_mutually_exclusive_group()
    formats.add_argument("--json", action="store_true", dest="json_output", default=argparse.SUPPRESS)
    formats.add_argument("--markdown", action="store_true", default=argparse.SUPPRESS, help="Export a Markdown report")
    common.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)
    common.add_argument(
        "--max-commits",
        type=positive_int,
        default=argparse.SUPPRESS,
        help="Maximum commits to inspect for history commands",
    )

    parser = ReportArgumentParser(
        json_errors=json_errors,
        prog="codegent",
        description="Trace the evolutionary lineage of code across git history.",
        parents=[common],
    )
    subparsers = parser.add_subparsers(dest="command", required=True,
                                       parser_class=partial(ReportArgumentParser, json_errors=json_errors))

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
    diff.add_argument("--summary", action="store_true", help="Show only aggregate comparison statistics")
    diff.add_argument("--path", action="append", default=[], dest="paths", help="Restrict diff to a literal file/directory (repeatable)")
    diff.set_defaults(handler=_cmd_diff)

    authors = subparsers.add_parser("authors", parents=[common], help="Summarize authors and churn for a file")
    authors.add_argument("path")
    authors.add_argument("--sort", choices=("commits", "churn", "name"), default="commits")
    authors.add_argument("--limit", type=positive_int, default=20)
    authors.set_defaults(handler=_cmd_authors)

    hotspots = subparsers.add_parser("hotspots", parents=[common], help="Rank historical paths by change activity")
    hotspots.add_argument("path", nargs="?", default=".")
    hotspots.add_argument("--sort", choices=("churn", "commits"), default="churn")
    hotspots.add_argument("--limit", type=positive_int, default=20)
    hotspots.add_argument("--min-commits", type=positive_int, default=1)
    hotspots.set_defaults(handler=_cmd_hotspots)

    owners = subparsers.add_parser("owners", parents=[common], help="Report surviving-line attribution at a commit")
    owners.add_argument("path")
    owners.add_argument("--lines", help="Inclusive START:END line range")
    owners.set_defaults(handler=_cmd_owners)

    return parser


def main(argv: list[str] | None = None) -> int:
    tokens = list(sys.argv[1:] if argv is None else argv)
    option_tokens = tokens[:tokens.index("--")] if "--" in tokens else tokens
    parser = build_parser(json_errors="--json" in option_tokens)
    args = parser.parse_args(tokens)
    provided = set(vars(args))
    _apply_defaults(args)
    if args.json_output and args.markdown:
        parser.error("choose one of --json and --markdown")
    invalid = {
        "diff": {"ref", "since", "until", "author", "follow", "first_parent", "max_commits", "mailmap"},
        "owners": {"since", "until", "author", "follow", "first_parent", "max_commits", "rename_threshold", "mailmap"},
        "hotspots": {"follow"},
    }.get(args.command, set())
    unsupported = sorted(provided & invalid)
    if unsupported:
        flags = ["--no-follow" if key == "follow" else "--" + key.replace("_", "-") for key in unsupported]
        parser.error(f"{args.command} does not support {', '.join(flags)}")
    color = supports_color(args.no_color) and not (args.json_output or args.markdown) and args.output in (None, "-")
    handler: Callable[[argparse.Namespace, bool], Any] = args.handler
    try:
        result = handler(args, color)
        if args.json_output:
            output = json.dumps(result, indent=2, sort_keys=True)
        elif args.markdown:
            output = render_markdown(result, args.command)
        else:
            output = result
        _write_output(output, args.output)
    except BrokenPipeError:
        # Redirect the descriptor so shutdown cannot flush the closed pipe again.
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
        return 0
    except UnicodeError:
        return _error("output cannot be encoded; use a UTF-8 terminal or --output FILE", json_output=args.json_output, color=False)
    except OSError as exc:
        return _error(str(exc), json_output=args.json_output, color=False)
    except GitError as exc:
        return _error(str(exc), json_output=args.json_output, color=color)
    except KeyboardInterrupt:
        return _error("interrupted", json_output=args.json_output, color=color)

    return 0


def _write_output(text: str, destination: str | None) -> None:
    if not text.endswith("\n"):
        text += "\n"
    if destination in (None, "-"):
        print(text, end="")
        sys.stdout.flush()
        return
    target = Path(destination).expanduser()
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=target.parent, prefix=".codegent-", delete=False) as stream:
            temporary = stream.name
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        raise GitError(f"cannot write report to {str(target)!r}: {exc.strerror or exc}") from exc
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _apply_defaults(args: argparse.Namespace) -> None:
    defaults = {
        "ref": "HEAD", "repo": ".", "json_output": False, "markdown": False, "no_color": False,
        "max_commits": 10000, "since": None, "until": None, "author": None, "follow": True, "first_parent": False, "rename_threshold": 50, "timeout": 30.0, "ignore_whitespace": False, "mailmap": False, "output": None,
    }
    for key, value in defaults.items():
        if not hasattr(args, key):
            setattr(args, key, value)


def _history_options(args: argparse.Namespace) -> dict[str, Any]:
    return {"max_commits": args.max_commits, "since": args.since, "until": args.until, "author": args.author, "follow": args.follow, "first_parent": args.first_parent}


def _tracer(args: argparse.Namespace) -> GitTracer:
    return GitTracer(args.repo, rename_threshold=args.rename_threshold, timeout=args.timeout, ignore_whitespace=args.ignore_whitespace, mailmap=args.mailmap)


def _history(args: argparse.Namespace):
    positional_ref = getattr(args, "commit_hash", None)
    if positional_ref and args.ref != "HEAD" and positional_ref != args.ref:
        raise GitError("choose either a positional commit or --ref, not conflicting refs")
    return _tracer(args).trace_path(
        args.path, positional_ref or args.ref, **_history_options(args),
    )


def _cmd_trace(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    bloodline = _history(args)
    if args.json_output or args.markdown:
        return bloodline.to_dict()
    return render_trace(bloodline, color=color)


def _cmd_ancestry(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    bloodline = _history(args)
    if args.json_output or args.markdown:
        return bloodline.to_dict()
    return render_ancestry(bloodline, color=color)


def _cmd_genemap(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    bloodline = _history(args)
    if args.json_output or args.markdown:
        return bloodline.to_dict()
    return render_genemap(bloodline, color=color)


def _cmd_bloodline(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    bloodline = _history(args)
    if args.json_output or args.markdown:
        return bloodline.to_dict()
    return "\n" + render_bloodline_summary(bloodline, color=color) + "\n"


def _cmd_diff(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    diff = _tracer(args).diff_lineage(args.commit_a, args.commit_b, paths=args.paths)
    if args.summary:
        report = diff.to_dict()
        report.pop("files")
        report.pop("stat")
        if args.json_output or args.markdown:
            return report
        summary = diff.summary
        return (f"{summary['files']} files: +{summary['additions']} -{summary['deletions']} lines; "
                f"{summary['binary_files']} binary files\n" +
                ", ".join(f"{key}={value}" for key, value in sorted(summary["statuses"].items())))
    if args.json_output or args.markdown:
        return diff.to_dict()
    return render_diff_lineage(diff, color=color)


def _cmd_authors(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    report = author_report(_history(args), sort=args.sort, limit=args.limit)
    return report if args.json_output or args.markdown else render_authors(report)


def _cmd_hotspots(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    history = _tracer(args).repository_history(args.path, args.ref, **_history_options(args))
    report = hotspot_report(history, limit=args.limit, sort=args.sort, min_commits=args.min_commits)
    return report if args.json_output or args.markdown else render_hotspots(report)


def _cmd_owners(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    report = _tracer(args).owners(args.path, args.ref, lines=args.lines)
    return report if args.json_output or args.markdown else render_owners(report)


def _error(message: str, *, json_output: bool, color: bool) -> int:
    if json_output:
        print(json.dumps({"error": message}), file=sys.stderr)
    else:
        print(danger(f"codegent: {escape_text(message)}", color), file=sys.stderr)
    return 1
