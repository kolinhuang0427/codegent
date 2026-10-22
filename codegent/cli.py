"""Command line interface for codegent."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
import stat
from functools import partial
import sys
from typing import Any, Callable

from .colors import danger, supports_color
from .exports import render_markdown
from .display import escape_text, ascii_graphics
from ._version import __version__
from .tracer import GitError, GitTracer, CHANGE_STATUSES
from .reports import author_report, render_authors, hotspot_report, render_hotspots, render_owners, timeline_report, render_timeline, cochange_report, render_cochange, render_files, render_source, render_doctor, render_refs, commit_range_report, render_commits, render_patch
from .tree import (
    render_ancestry,
    render_bloodline_summary,
    render_diff_lineage,
    render_genemap,
    render_trace,
)


def nonnegative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def _stream_text(message: str, stream) -> str:
    encoding = getattr(stream, "encoding", None) or "utf-8"
    return message.encode(encoding, "backslashreplace").decode(encoding)


class ReportArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, json_errors: bool = False, **kwargs):
        self.json_errors = json_errors
        super().__init__(*args, **kwargs)

    def _print_message(self, message, file=None):
        stream = file or sys.stderr
        if message:
            super()._print_message(_stream_text(message, stream), stream)

    def error(self, message: str) -> None:
        if self.json_errors:
            self.exit(2, json.dumps({"error": message}) + "\n")
        super().error(message)


def build_parser(*, json_errors: bool = False) -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--version", action="version", version=f"codegent {__version__}")
    common.add_argument("--no-clobber", action="store_true", default=argparse.SUPPRESS, help="Create an export only if its destination does not exist")
    common.add_argument("--output", default=argparse.SUPPRESS, help="Atomically write a report to a file; - means stdout")
    common.add_argument("--mailmap", action="store_true", default=argparse.SUPPRESS, help="Canonicalize history authors with .mailmap")
    common.add_argument("--ignore-whitespace", action="store_true", default=argparse.SUPPRESS, help="Ignore whitespace in textual change statistics")
    common.add_argument("--timeout", type=float, default=argparse.SUPPRESS, help="Timeout in seconds for each Git process (default: 30)")
    common.add_argument("--rename-threshold", type=int, default=argparse.SUPPRESS, help="Rename similarity percentage, 1-100 (default: 50)")
    common.add_argument("--first-parent", action="store_true", default=argparse.SUPPRESS, help="Follow the integration branch through merges")
    common.add_argument("--newest-first", action="store_true", default=argparse.SUPPRESS, help="Present file history from newest to oldest")
    common.add_argument("--no-follow", action="store_false", dest="follow", default=argparse.SUPPRESS, help="Stop at the current filename")
    common.add_argument("--grep", default=argparse.SUPPRESS, help="Literal commit-message substring")
    common.add_argument("--author", default=argparse.SUPPRESS, help="Literal author name/email substring")
    common.add_argument("--since", default=argparse.SUPPRESS, help="Include commits since an ISO date (UTC if unspecified)")
    common.add_argument("--until", default=argparse.SUPPRESS, help="Include commits up to an ISO date")
    common.add_argument("--ref", default=argparse.SUPPRESS, help="History tip (default: HEAD)")
    common.add_argument("--repo", default=argparse.SUPPRESS, help="Git repository path")
    formats = common.add_mutually_exclusive_group()
    formats.add_argument("--json", action="store_true", dest="json_output", default=argparse.SUPPRESS)
    formats.add_argument("--markdown", action="store_true", default=argparse.SUPPRESS, help="Export a Markdown report")
    common.add_argument("--compact", action="store_true", default=argparse.SUPPRESS, help="Emit single-line JSON reports (requires --json)")
    common.add_argument("--ascii", action="store_true", default=argparse.SUPPRESS, help="Use plain ASCII drawing characters in terminal reports")
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
    diff.add_argument("--status", choices=sorted(CHANGE_STATUSES), action="append", default=[], help="Include selected change statuses (repeatable)")
    diff.add_argument("--find-copies", action="store_true", help="Detect copies, including from unchanged source files")
    diff.add_argument("--merge-base", action="store_true", help="Compare the shared ancestor against the target")
    diff.add_argument("--summary", action="store_true", help="Show only aggregate comparison statistics")
    diff.add_argument("--path", action="append", default=[], dest="paths", help="Restrict diff to a literal file/directory (repeatable)")
    diff.set_defaults(handler=_cmd_diff)

    authors = subparsers.add_parser("authors", parents=[common], help="Summarize authors and churn for a file")
    authors.add_argument("path")
    authors.add_argument("--group-by", choices=("identity", "email"), default="identity", help="Combine name variants sharing an email")
    authors.add_argument("--sort", choices=("commits", "churn", "name"), default="commits")
    authors.add_argument("--min-commits", type=positive_int, default=1)
    authors.add_argument("--limit", type=positive_int, default=20)
    authors.set_defaults(handler=_cmd_authors)

    hotspots = subparsers.add_parser("hotspots", parents=[common], help="Rank historical paths by change activity")
    hotspots.add_argument("path", nargs="?", default=".")
    hotspots.add_argument("--current-only", action="store_true", help="Keep only paths present at the selected tip")
    hotspots.add_argument("--exclude", action="append", default=[], help="Exclude a root-relative path glob (repeatable)")
    hotspots.add_argument("--sort", choices=("churn", "commits"), default="churn")
    hotspots.add_argument("--limit", type=positive_int, default=20)
    hotspots.add_argument("--min-commits", type=positive_int, default=1)
    hotspots.set_defaults(handler=_cmd_hotspots)

    owners = subparsers.add_parser("owners", parents=[common], help="Report surviving-line attribution at a commit")
    owners.add_argument("path")
    owners.add_argument("--max-bytes", type=positive_int, default=1048576, help="Maximum blob size before attribution (default: 1 MiB)")
    owners.add_argument("--detect-moves", action="store_true", help="Retain attribution across within-file moved blocks")
    owners.add_argument("--ignore-revs-file", help="Ignore listed mechanical commits when attributing lines")
    owners.add_argument("--lines", help="Inclusive START:END line range")
    owners.set_defaults(handler=_cmd_owners)

    timeline = subparsers.add_parser("timeline", parents=[common], help="Summarize activity by UTC author-date periods")
    timeline.add_argument("path", nargs="?", default=".")
    timeline.add_argument("--date-basis", choices=("author", "committer"), default="author")
    timeline.add_argument("--period", choices=("day", "month", "year"), default="month")
    timeline.add_argument("--fill-gaps", action="store_true", help="Include empty periods between observed dates")
    timeline.add_argument("--max-periods", type=positive_int, default=1000)
    timeline.set_defaults(handler=_cmd_timeline)

    cochange = subparsers.add_parser("cochange", parents=[common], help="Find files changed in the same commits as a target")
    cochange.add_argument("path")
    cochange.add_argument("--limit", type=positive_int, default=20)
    cochange.add_argument("--min-shared", type=positive_int, default=1)
    cochange.set_defaults(handler=_cmd_cochange)

    files = subparsers.add_parser("files", parents=[common], help="List tracked files and object metadata at a commit")
    files.add_argument("path", nargs="?", default=".")
    files.add_argument("--limit", type=positive_int, default=1000)
    files.add_argument("--sort", choices=("path", "size"), default="path")
    files.add_argument("--kind", choices=("all", "file", "executable", "symlink", "submodule"), default="all")
    files.set_defaults(handler=_cmd_files)

    source = subparsers.add_parser("source", parents=[common], help="Preview a bounded text blob at a commit")
    source.add_argument("path")
    source.add_argument("--lines", help="Inclusive START:END line range")
    source.add_argument("--max-bytes", type=positive_int, default=1048576)
    source.set_defaults(handler=_cmd_source)

    doctor = subparsers.add_parser("doctor", parents=[common], help="Inspect Git and worktree readiness without changing files")
    doctor.set_defaults(handler=_cmd_doctor)

    refs = subparsers.add_parser("refs", parents=[common], help="Browse branch, tag, and remote-tracking references")
    refs.add_argument("--kind", choices=("all", "branch", "tag", "remote"), default="all")
    refs.add_argument("--limit", type=positive_int, default=1000)
    refs.set_defaults(handler=_cmd_refs)

    commits = subparsers.add_parser("commits", parents=[common], help="List commits reachable from TARGET but not BASE")
    commits.add_argument("base")
    commits.add_argument("target")
    commits.add_argument("--path", default=".", help="Optional literal file or directory scope")
    commits.set_defaults(handler=_cmd_commits)

    patch = subparsers.add_parser("patch", parents=[common], help="Preview a size-limited unified patch between revisions")
    patch.add_argument("base")
    patch.add_argument("target")
    patch.add_argument("--path", action="append", default=[], dest="paths")
    patch.add_argument("--context", type=nonnegative_int, default=3)
    patch.add_argument("--max-bytes", type=positive_int, default=1048576)
    patch.set_defaults(handler=_cmd_patch)

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
    if args.compact and not args.json_output:
        parser.error("--compact requires --json")
    if args.no_clobber and args.output in (None, "-"):
        parser.error("--no-clobber requires a file --output destination")
    invalid = {
        "diff": {"ref", "since", "until", "author", "grep", "follow", "first_parent", "max_commits", "mailmap"},
        "owners": {"since", "until", "author", "grep", "follow", "first_parent", "max_commits", "rename_threshold", "mailmap"},
        "hotspots": {"follow"},
        "timeline": {"follow"},
        "cochange": {"follow"},
        "commits": {"ref", "follow"},
        "patch": {"ref", "since", "until", "author", "grep", "follow", "first_parent", "max_commits", "mailmap"},
        "refs": {"ref", "since", "until", "author", "grep", "follow", "first_parent", "max_commits", "rename_threshold", "mailmap", "ignore_whitespace"},
        "doctor": {"ref", "since", "until", "author", "grep", "follow", "first_parent", "max_commits", "rename_threshold", "mailmap", "ignore_whitespace"},
        "source": {"since", "until", "author", "grep", "follow", "first_parent", "max_commits", "rename_threshold", "mailmap", "ignore_whitespace"},
        "files": {"since", "until", "author", "grep", "follow", "first_parent", "max_commits", "rename_threshold", "mailmap", "ignore_whitespace"},
    }.get(args.command, set())
    if args.command not in {"trace", "ancestry", "genemap", "bloodline", "commits"}:
        invalid = invalid | {"newest_first"}
    unsupported = sorted(provided & invalid)
    if unsupported:
        flags = ["--no-follow" if key == "follow" else "--" + key.replace("_", "-") for key in unsupported]
        parser.error(f"{args.command} does not support {', '.join(flags)}")
    color = supports_color(args.no_color or args.ascii) and not (args.json_output or args.markdown) and args.output in (None, "-")
    handler: Callable[[argparse.Namespace, bool], Any] = args.handler
    try:
        result = handler(args, color)
        if args.json_output:
            output = json.dumps(result, indent=None if args.compact else 2,
                                separators=(",", ":") if args.compact else None, sort_keys=True)
        elif args.markdown:
            output = render_markdown(result, args.command)
        else:
            output = ascii_graphics(result) if args.ascii else result
        _write_output(output, args.output, no_clobber=args.no_clobber)
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


def _write_output(text: str, destination: str | None, *, no_clobber: bool = False) -> None:
    if not text.endswith("\n"):
        text += "\n"
    if destination in (None, "-"):
        print(text, end="")
        sys.stdout.flush()
        return
    target = Path(destination).expanduser()
    temporary: str | None = None
    try:
        try:
            target_stat = target.lstat()
            existing_mode = target_stat.st_mode & 0o777 if stat.S_ISREG(target_stat.st_mode) else None
        except FileNotFoundError:
            existing_mode = None
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=target.parent, prefix=".codegent-", delete=False) as stream:
            temporary = stream.name
            stream.write(text)
            stream.flush()
            if existing_mode is not None and not no_clobber:
                os.fchmod(stream.fileno(), existing_mode)
            os.fsync(stream.fileno())
        if no_clobber:
            os.link(temporary, target)  # Atomic exclusive creation on the same filesystem.
        else:
            os.replace(temporary, target)
    except OSError as exc:
        raise GitError(f"cannot write report to {str(target)!r}: {exc.strerror or exc}") from exc
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _apply_defaults(args: argparse.Namespace) -> None:
    defaults = {
        "ref": "HEAD", "repo": ".", "json_output": False, "markdown": False, "no_color": False, "ascii": False, "compact": False, "no_clobber": False,
        "max_commits": 10000, "since": None, "until": None, "author": None, "grep": None, "follow": True, "newest_first": False, "first_parent": False, "rename_threshold": 50, "timeout": 30.0, "ignore_whitespace": False, "mailmap": False, "output": None,
    }
    for key, value in defaults.items():
        if not hasattr(args, key):
            setattr(args, key, value)


def _history_options(args: argparse.Namespace) -> dict[str, Any]:
    return {"max_commits": args.max_commits, "since": args.since, "until": args.until, "author": args.author, "grep": args.grep, "follow": args.follow, "first_parent": args.first_parent, "newest_first": args.newest_first}


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
    diff = _tracer(args).diff_lineage(args.commit_a, args.commit_b, paths=args.paths, merge_base=args.merge_base, find_copies=args.find_copies, statuses=args.status)
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
    report = author_report(_history(args), sort=args.sort, limit=args.limit, group_by=args.group_by, min_commits=args.min_commits)
    return report if args.json_output or args.markdown else render_authors(report)


def _cmd_hotspots(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    tracer = _tracer(args)
    history = tracer.repository_history(args.path, args.ref, **_history_options(args))
    current_paths = None
    if args.current_only:
        current_paths = set(tracer.git(["ls-tree", "-r", "--name-only", "-z", history.resolved_ref]).split("\0")) - {""}
    report = hotspot_report(history, limit=args.limit, sort=args.sort, min_commits=args.min_commits, excludes=args.exclude, current_paths=current_paths)
    return report if args.json_output or args.markdown else render_hotspots(report)


def _cmd_owners(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    report = _tracer(args).owners(args.path, args.ref, lines=args.lines, ignore_revs_file=args.ignore_revs_file, detect_moves=args.detect_moves, max_bytes=args.max_bytes)
    return report if args.json_output or args.markdown else render_owners(report)


def _cmd_timeline(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    history = _tracer(args).repository_history(args.path, args.ref, **_history_options(args))
    report = timeline_report(history, period=args.period, date_basis=args.date_basis, fill_gaps=args.fill_gaps, max_periods=args.max_periods)
    return report if args.json_output or args.markdown else render_timeline(report)


def _cmd_cochange(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    tracer = _tracer(args)
    path = tracer.normalize_path(args.path)
    history = tracer.repository_history(tracer.root(), args.ref, **_history_options(args))
    report = cochange_report(history, path, limit=args.limit, min_shared=args.min_shared)
    return report if args.json_output or args.markdown else render_cochange(report)


def _cmd_files(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    report = _tracer(args).tracked_files(args.path, args.ref, limit=args.limit, sort=args.sort, kind=args.kind)
    return report if args.json_output or args.markdown else render_files(report)


def _cmd_source(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    report = _tracer(args).source(args.path, args.ref, lines=args.lines, max_bytes=args.max_bytes)
    return report if args.json_output or args.markdown else render_source(report)


def _cmd_doctor(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    report = _tracer(args).doctor()
    return report if args.json_output or args.markdown else render_doctor(report)


def _cmd_refs(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    report = _tracer(args).refs(kind=args.kind, limit=args.limit)
    return report if args.json_output or args.markdown else render_refs(report)


def _cmd_commits(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    history = _tracer(args).repository_history(args.path, args.target, exclude_ref=args.base, **_history_options(args))
    report = commit_range_report(history)
    return report if args.json_output or args.markdown else render_commits(report)


def _cmd_patch(args: argparse.Namespace, color: bool) -> dict[str, Any] | str:
    report = _tracer(args).patch(args.base, args.target, paths=args.paths, context=args.context, max_bytes=args.max_bytes)
    return report if args.json_output or args.markdown else render_patch(report)


def _error(message: str, *, json_output: bool, color: bool) -> int:
    rendered = json.dumps({"error": message}) if json_output else danger(f"codegent: {escape_text(message)}", color)
    print(_stream_text(rendered, sys.stderr), file=sys.stderr)
    return 1
