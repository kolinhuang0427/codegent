"""Maintainer reports derived from observed repository history."""
from __future__ import annotations

from typing import Any
from fnmatch import fnmatchcase

from .display import safe_display
from .models import Bloodline
from .tracer import iso_date, positive_count, GitError


def author_report(bloodline: Bloodline, *, sort: str = "commits", limit: int = 20, group_by: str = "identity", min_commits: int = 1) -> dict[str, Any]:
    positive_count(limit, "limit")
    positive_count(min_commits, "min_commits")
    if sort not in {"commits", "churn", "name"}:
        raise GitError("invalid author sort; choose commits, churn, or name")
    if group_by not in {"identity", "email"}:
        raise GitError("author grouping must be identity or email")
    authors: dict[str, dict[str, Any]] = {}
    for commit in bloodline.commits:
        identity = commit.author_email.casefold() if group_by == "email" and commit.author_email else commit.author
        row = authors.setdefault(identity, {
            "author": identity, "identities": [], "commits": 0, "additions": 0, "deletions": 0,
            "binary_changes": 0, "first_seen": commit.date, "last_seen": commit.date,
        })
        if commit.author not in row["identities"]:
            row["identities"].append(commit.author)
        row["commits"] += 1
        row["additions"] += commit.additions
        row["deletions"] += commit.deletions
        row["binary_changes"] += int(commit.binary)
        if iso_date(commit.date) < iso_date(row["first_seen"]):
            row["first_seen"] = commit.date
        if iso_date(commit.date) > iso_date(row["last_seen"]):
            row["last_seen"] = commit.date
    for row in authors.values():
        row["churn"] = row["additions"] + row["deletions"]
    rows = sorted((row for row in authors.values() if row["commits"] >= min_commits), key=lambda row: (
        0 if sort == "name" else -row[sort], row["author"].casefold(), row["author"],
    ))
    return {
        "path": bloodline.path, "repo": bloodline.repo, "requested_ref": bloodline.requested_ref, "resolved_ref": bloodline.resolved_ref,
        "history_complete": bloodline.history_complete, "warnings": bloodline.warnings,
        "selection": bloodline.selection, "total_commits": len(bloodline.commits),
        "total_authors": len(authors), "matching_authors": len(rows), "displayed_authors": len(rows[:limit]),
        "omitted_authors": len(authors) - len(rows[:limit]), "min_commits": min_commits,
        "authors": rows[:limit], "sort": sort, "group_by": group_by,
    }


@safe_display
def render_authors(report: dict[str, Any]) -> str:
    lines = [f"Authors: {report['path']}", "Commits  Churn  Author"]
    lines.extend(f"{row['commits']:7}  {row['churn']:5}  {row['author']}" for row in report["authors"])
    lines.append(f"Showing {report['displayed_authors']} of {report['total_authors']} authors (minimum {report['min_commits']} commits)")
    lines.extend(f"Warning: {warning}" for warning in report["warnings"])
    return "\n".join(lines) + "\n"


def hotspot_report(history: Bloodline, *, limit: int = 20, sort: str = "churn", min_commits: int = 1, excludes: list[str] | None = None, current_paths: set[str] | None = None) -> dict[str, Any]:
    positive_count(limit, "limit")
    positive_count(min_commits, "min_commits")
    if sort not in {"commits", "churn"}:
        raise GitError("invalid hotspot sort; choose commits or churn")
    files: dict[str, dict[str, Any]] = {}
    for commit in history.commits:
        for item in commit.changes:
            row = files.setdefault(item["path"], {
                "path": item["path"], "commits": 0, "additions": 0, "deletions": 0, "binary_changes": 0,
            })
            row["commits"] += 1
            row["additions"] += item["additions"]
            row["deletions"] += item["deletions"]
            row["binary_changes"] += int(item["binary"])
    for row in files.values():
        row["churn"] = row["additions"] + row["deletions"]
    rows = sorted((row for row in files.values() if row["commits"] >= min_commits
                   and (current_paths is None or row["path"] in current_paths)
                   and not any(fnmatchcase(row["path"], pattern) for pattern in (excludes or []))),
                  key=lambda row: (-row[sort], row["path"]))
    return {
        "repo": history.repo, "path": history.path, "requested_ref": history.requested_ref, "resolved_ref": history.resolved_ref,
        "history_complete": history.history_complete, "warnings": history.warnings,
        "selection": history.selection, "scanned_commits": len(history.commits),
        "matching_files": len(rows), "files": rows[:limit], "sort": sort, "excludes": excludes or [], "current_only": current_paths is not None,
        "path_policy": "historical names are counted separately across renames",
    }


@safe_display
def render_hotspots(report: dict[str, Any]) -> str:
    lines = [f"Hotspots: {report['path']}", "Churn  Commits  Path"]
    lines.extend(f"{row['churn']:5}  {row['commits']:7}  {row['path']}" for row in report["files"])
    lines.extend(f"Warning: {warning}" for warning in report["warnings"])
    lines.append(report["path_policy"])
    return "\n".join(lines) + "\n"


@safe_display
def render_owners(report: dict[str, Any]) -> str:
    lines = [f"Line ownership: {report['path']} ({report['selected_lines']} lines)", "Lines  Percent  Author"]
    lines.extend(f"{row['lines']:5}  {row['percentage']:6.2f}%  {row['author']}" for row in report["owners"])
    lines.extend(f"Warning: {warning}" for warning in report.get("warnings", []))
    lines.append(report["attribution"])
    return "\n".join(lines) + "\n"


def timeline_report(history: Bloodline, *, period: str = "month", date_basis: str = "author") -> dict[str, Any]:
    widths = {"day": 10, "month": 7, "year": 4}
    if period not in widths:
        raise GitError("timeline period must be day, month, or year")
    if date_basis not in {"author", "committer"}:
        raise GitError("timeline date basis must be author or committer")
    buckets: dict[str, dict[str, Any]] = {}
    for commit in history.commits:
        date = commit.date if date_basis == "author" else commit.committer_date
        if not date:
            raise GitError("requested timeline dates are unavailable in supplied history")
        key = iso_date(date)[:widths[period]]
        row = buckets.setdefault(key, {"period": key, "commits": 0, "authors": set(), "files": set(),
                                       "additions": 0, "deletions": 0, "binary_changes": 0})
        row["commits"] += 1
        row["authors"].add(commit.author)
        row["files"].update(commit.files)
        row["additions"] += commit.additions
        row["deletions"] += commit.deletions
        row["binary_changes"] += sum(int(item["binary"]) for item in commit.changes)
    rows = [buckets[key] for key in sorted(buckets)]
    for row in rows:
        row["authors"] = len(row["authors"])
        row["files"] = len(row["files"])
    return {"repo": history.repo, "path": history.path, "requested_ref": history.requested_ref,
            "resolved_ref": history.resolved_ref, "history_complete": history.history_complete,
            "selection": history.selection, "warnings": history.warnings, "period": period,
            "date_basis": f"{date_basis} dates normalized to UTC", "date_basis_key": date_basis, "periods": rows}


@safe_display
def render_timeline(report: dict[str, Any]) -> str:
    lines = [f"Activity timeline: {report['path']} ({report['date_basis']})", "Period  Commits  Authors  Files  +Lines  -Lines"]
    lines.extend(f"{row['period']}  {row['commits']:7}  {row['authors']:7}  {row['files']:5}  {row['additions']:6}  {row['deletions']:6}" for row in report["periods"])
    lines.extend(f"Warning: {warning}" for warning in report["warnings"])
    return "\n".join(lines) + "\n"


def cochange_report(history: Bloodline, path: str, *, limit: int = 20, min_shared: int = 1) -> dict[str, Any]:
    positive_count(limit, "limit")
    positive_count(min_shared, "min_shared")
    counts: dict[str, int] = {}
    target_commits = 0
    for commit in history.commits:
        matches = lambda item: item["path"] == path or item.get("renamed_from") == path
        if not any(matches(item) for item in commit.changes):
            continue
        target_commits += 1
        companions = {item["path"] for item in commit.changes if not matches(item)}
        for companion in companions:
            counts[companion] = counts.get(companion, 0) + 1
    rows = [{"path": candidate, "shared_commits": count, "fraction": round(count / target_commits, 4)}
            for candidate, count in counts.items() if count >= min_shared]
    rows.sort(key=lambda row: (-row["shared_commits"], row["path"]))
    return {"repo": history.repo, "path": path, "requested_ref": history.requested_ref,
            "resolved_ref": history.resolved_ref, "history_complete": history.history_complete,
            "selection": history.selection, "warnings": history.warnings, "target_commits": target_commits,
            "scanned_commits": len(history.commits), "matching_files": len(rows), "files": rows[:limit],
            "interpretation": "same-commit co-occurrence, not a dependency or causal relationship"}


@safe_display
def render_cochange(report: dict[str, Any]) -> str:
    lines = [f"Files changed with: {report['path']} ({report['target_commits']} target commits)", "Shared  Fraction  Path"]
    lines.extend(f"{row['shared_commits']:6}  {row['fraction']:8.4f}  {row['path']}" for row in report["files"])
    lines.extend(f"Warning: {warning}" for warning in report["warnings"])
    lines.append(report["interpretation"])
    return "\n".join(lines) + "\n"


@safe_display
def render_files(report: dict[str, Any]) -> str:
    lines = [f"Tracked files: {report['path']} at {report['resolved_ref'][:12]}", "Mode  Type  Bytes  Path"]
    lines.extend(f"{row['mode']}  {row['type']}  {row['size'] if row['size'] is not None else '-'}  {row['path']}" for row in report["files"])
    lines.append(f"Showing {len(report['files'])} of {report['total_files']} entries")
    return "\n".join(lines) + "\n"


@safe_display
def render_source(report: dict[str, Any]) -> str:
    lines = [f"Source: {report['path']} at {report['resolved_ref'][:12]}"]
    lines.extend(f"{row['number']:6}  {row['text']}" for row in report["lines"])
    return "\n".join(lines) + "\n"


@safe_display
def render_doctor(report: dict[str, Any]) -> str:
    return "Repository diagnostics\n" + "\n".join(f"{key}: {value}" for key, value in report.items()) + "\n"


@safe_display
def render_refs(report: dict[str, Any]) -> str:
    lines = ["Repository references", "Kind  Ref  Object type  Object ID"]
    lines.extend(f"{row['kind']}  {row['ref']}  {row['object_type']}  {row['object_id']}" for row in report["refs"])
    lines.append(f"Showing {len(report['refs'])} of {report['total_refs']} references")
    return "\n".join(lines) + "\n"


def commit_range_report(history: Bloodline) -> dict[str, Any]:
    commits = [dict(commit.to_dict(), role="selected") for commit in history.display_commits]
    return {"repo": history.repo, "path": history.path, "requested_ref": history.requested_ref,
            "resolved_ref": history.resolved_ref, "commit_a": history.selection["excluded_ref"],
            "commit_b": history.requested_ref, "excluded_resolved": history.selection["excluded_resolved"],
            "selection": history.selection, "truncated": history.truncated, "shallow": history.shallow,
            "range_complete": not (history.truncated or history.shallow) and set(history.selection) <= {"excluded_ref", "excluded_resolved"},
            "warnings": [warning for warning in history.warnings if not warning.startswith("The earliest observed")],
            "order": "newest-first" if history.newest_first else "oldest-first", "total_commits": len(commits), "commits": commits}


@safe_display
def render_commits(report: dict[str, Any]) -> str:
    lines = [f"Commits in {report['commit_b']} excluding {report['commit_a']}: {report['total_commits']}"]
    lines.extend(f"{row['short_hash']}  {row['author_name']}  {row['message']}" for row in report["commits"])
    lines.extend(f"Warning: {warning}" for warning in report["warnings"])
    return "\n".join(lines) + "\n"


def render_patch(report: dict[str, Any]) -> str:
    from .display import escape_text
    title = escape_text(f"Patch preview: {report['commit_a']} -> {report['commit_b']}")
    content = "\n".join(escape_text(line) for line in report["patch"].split("\n"))
    return title + "\n" + (content or "No changes.\n")
