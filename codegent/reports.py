"""Maintainer reports derived from observed repository history."""
from __future__ import annotations

from datetime import date as calendar_date, timedelta
from typing import Any
from fnmatch import fnmatchcase

from .display import safe_display
from .models import Bloodline
from .tracer import iso_date, positive_count, nonnegative_count, GitError


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
        "rename_threshold": bloodline.rename_threshold, "mailmap": bloodline.mailmap,
        "max_commits": bloodline.max_commits, "followed_renames": bloodline.followed_renames,
        "authors": rows[:limit], "sort": sort, "group_by": group_by,
    }


@safe_display
def render_authors(report: dict[str, Any]) -> str:
    lines = [f"Authors: {report['path']}", "Commits  Churn  Author"]
    lines.extend(f"{row['commits']:7}  {row['churn']:5}  {row['author']}" for row in report["authors"])
    lines.append(f"Showing {report['displayed_authors']} of {report['total_authors']} authors (minimum {report['min_commits']} commits)")
    lines.extend(f"Warning: {warning}" for warning in report["warnings"])
    return "\n".join(lines) + "\n"


def hotspot_report(history: Bloodline, *, limit: int = 20, sort: str = "churn", min_commits: int = 1, excludes: list[str] | None = None, current_paths: set[str] | None = None, includes: list[str] | None = None, min_churn: int = 0) -> dict[str, Any]:
    positive_count(limit, "limit")
    positive_count(min_commits, "min_commits")
    if sort not in {"commits", "churn", "authors", "recent"}:
        raise GitError("invalid hotspot sort; choose commits, churn, authors, or recent")
    nonnegative_count(min_churn, "min_churn")
    files: dict[str, dict[str, Any]] = {}
    for commit in history.commits:
        for item in commit.changes:
            row = files.setdefault(item["path"], {
                "path": item["path"], "commits": 0, "additions": 0, "deletions": 0, "binary_changes": 0,
                "authors": set(), "first_changed": iso_date(commit.committer_date or commit.date),
                "last_changed": iso_date(commit.committer_date or commit.date),
            })
            row["commits"] += 1
            row["additions"] += item["additions"]
            row["deletions"] += item["deletions"]
            row["binary_changes"] += int(item["binary"])
            row["authors"].add(commit.author)
            changed = iso_date(commit.committer_date or commit.date)
            row["first_changed"] = min(row["first_changed"], changed)
            row["last_changed"] = max(row["last_changed"], changed)
    for row in files.values():
        row["authors"] = len(row["authors"])
        row["churn"] = row["additions"] + row["deletions"]
    rows = sorted((row for row in files.values() if row["commits"] >= min_commits and row["churn"] >= min_churn
                   and (current_paths is None or row["path"] in current_paths)
                   and (not includes or any(fnmatchcase(row["path"], pattern) for pattern in includes))
                   and not any(fnmatchcase(row["path"], pattern) for pattern in (excludes or []))),
                  key=lambda row: (0 if sort == "recent" else -row[sort], row["path"]))
    if sort == "recent":
        rows.sort(key=lambda row: row["last_changed"], reverse=True)
    return {
        "repo": history.repo, "path": history.path, "requested_ref": history.requested_ref, "resolved_ref": history.resolved_ref,
        "history_complete": history.history_complete, "warnings": history.warnings,
        "selection": history.selection, "scanned_commits": len(history.commits),
        "matching_files": len(rows), "min_churn": min_churn, "min_commits": min_commits, "files": rows[:limit], "sort": sort, "includes": includes or [], "excludes": excludes or [], "current_only": current_paths is not None,
        "date_basis": "UTC committer dates within selected history",
        "path_policy": "historical names are counted separately across renames",
    }


@safe_display
def render_hotspots(report: dict[str, Any]) -> str:
    lines = [f"Hotspots: {report['path']}", "Churn  Commits  Authors  Last changed  Path"]
    lines.extend(f"{row['churn']:5}  {row['commits']:7}  {row['authors']:7}  {row['last_changed']}  {row['path']}" for row in report["files"])
    lines.extend(f"Warning: {warning}" for warning in report["warnings"])
    lines.append(report["path_policy"])
    return "\n".join(lines) + "\n"


@safe_display
def render_owners(report: dict[str, Any]) -> str:
    lines = [f"Line ownership: {report['path']} ({report['selected_lines']} lines)", "Lines  Percent  Author"]
    lines.extend(f"{row['lines']:5}  {row['percentage']:6.2f}%  {row['author']}" + (f"  {row['commit']}" if "commit" in row else "") for row in report["owners"])
    if report.get("show_lines"):
        lines.extend(f"{row['author']} ranges: {row['line_ranges']}" for row in report["owners"])
    lines.extend(f"Warning: {warning}" for warning in report.get("warnings", []))
    lines.append(f"Showing {report['displayed_groups']} of {report['total_groups']} groups; omitted lines: {report['omitted_lines']}")
    lines.append(report["attribution"])
    return "\n".join(lines) + "\n"


def timeline_report(history: Bloodline, *, period: str = "month", date_basis: str = "author", fill_gaps: bool = False, max_periods: int = 1000, cumulative: bool = False) -> dict[str, Any]:
    positive_count(max_periods, "max_periods")
    widths = {"day": 10, "week": 10, "month": 7, "year": 4}
    if period not in widths:
        raise GitError("timeline period must be day, week, month, or year")
    if date_basis not in {"author", "committer"}:
        raise GitError("timeline date basis must be author or committer")
    buckets: dict[str, dict[str, Any]] = {}
    for commit in history.commits:
        date = commit.date if date_basis == "author" else commit.committer_date
        if not date:
            raise GitError("requested timeline dates are unavailable in supplied history")
        normalized = iso_date(date)
        day = calendar_date.fromisoformat(normalized[:10])
        key = (day - timedelta(days=day.weekday())).isoformat() if period == "week" else normalized[:widths[period]]
        row = buckets.setdefault(key, {"period": key, "commits": 0, "authors": set(), "files": set(),
                                       "additions": 0, "deletions": 0, "binary_changes": 0})
        row["commits"] += 1
        row["authors"].add(commit.author)
        row["files"].update(commit.files)
        row["additions"] += commit.additions
        row["deletions"] += commit.deletions
        row["binary_changes"] += sum(int(item["binary"]) for item in commit.changes)
    if fill_gaps and buckets:
        first, last = min(buckets), max(buckets)
        current = calendar_date.fromisoformat(first + {"day": "", "week": "", "month": "-01", "year": "-01-01"}[period])
        while True:
            key = current.isoformat()[:widths[period]]
            if key > last:
                break
            buckets.setdefault(key, {"period": key, "commits": 0, "authors": set(), "files": set(),
                                     "additions": 0, "deletions": 0, "binary_changes": 0})
            if len(buckets) > max_periods:
                raise GitError("timeline exceeds --max-periods; increase the budget or narrow history")
            if key == last:
                break
            if period in {"day", "week"}:
                current += timedelta(days=7 if period == "week" else 1)
            elif period == "month":
                current = calendar_date(current.year + (current.month == 12), current.month % 12 + 1, 1)
            else:
                current = calendar_date(current.year + 1, 1, 1)
    if len(buckets) > max_periods:
        raise GitError("timeline exceeds --max-periods; increase the budget or narrow history")
    rows = [buckets[key] for key in sorted(buckets)]
    running = {"commits": 0, "additions": 0, "deletions": 0, "binary_changes": 0}
    for row in rows:
        if cumulative:
            for key in running:
                running[key] += row[key]
                row["cumulative_" + key] = running[key]
        row["authors"] = len(row["authors"])
        row["files"] = len(row["files"])
    return {"repo": history.repo, "path": history.path, "requested_ref": history.requested_ref,
            "resolved_ref": history.resolved_ref, "history_complete": history.history_complete,
            "selection": history.selection, "warnings": history.warnings, "period": period,
            "date_basis": f"{date_basis} dates normalized to UTC", "date_basis_key": date_basis, "week_start": "monday" if period == "week" else None, "fill_gaps": fill_gaps, "max_periods": max_periods, "cumulative": cumulative,
            "cumulative_scope": "selected commits in displayed period order; diff counts, not surviving lines", "periods": rows}


@safe_display
def render_timeline(report: dict[str, Any]) -> str:
    keys = ["period", "commits", "authors", "files", "additions", "deletions", "binary_changes"]
    headers = ["Period", "Commits", "Authors", "Files", "+Lines", "-Lines", "Binary changes"]
    if report["cumulative"]:
        keys += ["cumulative_" + key for key in ("commits", "additions", "deletions", "binary_changes")]
        headers += ["Total commits", "Total+", "Total-", "Total binary changes"]
    lines = [f"Activity timeline: {report['path']} ({report['date_basis']})", "  ".join(headers)]
    lines.extend("  ".join(str(row[key]) for key in keys) for row in report["periods"])
    lines.extend(f"Warning: {warning}" for warning in report["warnings"])
    if report["cumulative"]:
        lines.append(report["cumulative_scope"])
    return "\n".join(lines) + "\n"


def cochange_report(history: Bloodline, path: str, *, limit: int = 20, min_shared: int = 1, excludes: list[str] | None = None, min_fraction: float = 0, sort: str = "shared") -> dict[str, Any]:
    positive_count(limit, "limit")
    positive_count(min_shared, "min_shared")
    import math
    if isinstance(min_fraction, bool) or not isinstance(min_fraction, (int, float)) or not math.isfinite(min_fraction) or not 0 <= min_fraction <= 1:
        raise GitError("minimum cochange fraction must be finite and between 0 and 1")
    if sort not in {"shared", "jaccard", "path"}:
        raise GitError("cochange sort must be shared, jaccard, or path")
    candidate_commits: dict[str, int] = {}
    for commit in history.commits:
        for candidate in {item["path"] for item in commit.changes}:
            candidate_commits[candidate] = candidate_commits.get(candidate, 0) + 1
    counts: dict[str, int] = {}
    target_commits = 0
    for commit in history.commits:
        def in_scope(candidate):
            return candidate is not None and (path == "." or candidate == path or candidate.startswith(path + "/"))
        matches = lambda item: in_scope(item["path"]) or in_scope(item.get("renamed_from"))
        if not any(matches(item) for item in commit.changes):
            continue
        target_commits += 1
        companions = {item["path"] for item in commit.changes if not matches(item)}
        for companion in companions:
            counts[companion] = counts.get(companion, 0) + 1
    rows = [{"path": candidate, "shared_commits": count, "fraction": round(count / target_commits, 4),
             "candidate_commits": candidate_commits[candidate],
             "jaccard": round(count / (target_commits + candidate_commits[candidate] - count), 4)}
            for candidate, count in counts.items() if count >= min_shared and count / target_commits >= min_fraction
            and not any(fnmatchcase(candidate, pattern) for pattern in (excludes or []))]
    rows.sort(key=lambda row: (0 if sort == "path" else
                              -(row["shared_commits"] / (target_commits + row["candidate_commits"] - row["shared_commits"]) if sort == "jaccard" else row["shared_commits"]), row["path"]))
    return {"repo": history.repo, "path": path, "requested_ref": history.requested_ref,
            "resolved_ref": history.resolved_ref, "history_complete": history.history_complete,
            "selection": history.selection, "warnings": history.warnings, "target_commits": target_commits,
            "scanned_commits": len(history.commits), "sort": sort, "min_fraction": min_fraction, "min_shared": min_shared, "excludes": excludes or [], "matching_files": len(rows), "files": rows[:limit],
            "interpretation": "same-commit co-occurrence, not a dependency or causal relationship"}


@safe_display
def render_cochange(report: dict[str, Any]) -> str:
    lines = [f"Files changed with: {report['path']} ({report['target_commits']} target commits)", "Shared  Fraction  Jaccard  Path"]
    lines.extend(f"{row['shared_commits']:6}  {row['fraction']:8.4f}  {row['jaccard']:7.4f}  {row['path']}" for row in report["files"])
    lines.extend(f"Warning: {warning}" for warning in report["warnings"])
    lines.append(report["interpretation"])
    return "\n".join(lines) + "\n"


@safe_display
def render_files(report: dict[str, Any]) -> str:
    lines = [f"Tracked files: {report['path']} at {report['resolved_ref'][:12]}", "Mode  Type  Bytes  Object ID  Path"]
    lines.extend(f"{row['mode']}  {row['type']}  {row['size'] if row['size'] is not None else '-'}  {row['object_id']}  {row['path']}" for row in report["files"])
    lines.append(f"Showing {len(report['files'])} of {report['matching_files']} matching entries ({report['total_files']} before filters)")
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


def directory_report(history: Bloodline, *, depth: int = 1, limit: int = 20, sort: str = "churn", excludes: list[str] | None = None, min_commits: int = 1) -> dict[str, Any]:
    positive_count(depth, "depth")
    positive_count(limit, "limit")
    positive_count(min_commits, "min_commits")
    if sort not in {"churn", "commits", "path"}:
        raise GitError("directory sort must be churn, commits, or path")
    groups: dict[str, dict[str, Any]] = {}
    for commit in history.commits:
        touched = set()
        for change in commit.changes:
            if any(fnmatchcase(change["path"], pattern) for pattern in (excludes or [])):
                continue
            parent = "/".join(change["path"].split("/")[:-1][:depth]) or "."
            row = groups.setdefault(parent, {"path": parent, "commits": 0, "authors": set(), "files": set(),
                                             "additions": 0, "deletions": 0, "binary_changes": 0})
            row["files"].add(change["path"])
            row["authors"].add(commit.author)
            row["additions"] += change["additions"]
            row["deletions"] += change["deletions"]
            row["binary_changes"] += int(change["binary"])
            touched.add(parent)
        for parent in touched:
            groups[parent]["commits"] += 1
    for row in groups.values():
        row["authors"] = len(row["authors"])
        row["files"] = len(row["files"])
        row["churn"] = row["additions"] + row["deletions"]
    rows = sorted((row for row in groups.values() if row["commits"] >= min_commits), key=lambda row: (0 if sort == "path" else -row[sort], row["path"]))
    return {"repo": history.repo, "path": history.path, "requested_ref": history.requested_ref,
            "resolved_ref": history.resolved_ref, "selection": history.selection, "warnings": history.warnings,
            "history_complete": history.history_complete, "scanned_commits": len(history.commits),
            "depth": depth, "sort": sort, "excludes": excludes or [], "min_commits": min_commits, "matching_directories": len(rows), "total_directories": len(groups), "directories": rows[:limit],
            "path_policy": "root-relative historical destination paths; renamed names are not unified"}


@safe_display
def render_directories(report: dict[str, Any]) -> str:
    lines = [f"Directory activity: {report['path']}", "Commits  Churn  Files  Authors  Directory"]
    lines.extend(f"{r['commits']:7}  {r['churn']:5}  {r['files']:5}  {r['authors']:7}  {r['path']}" for r in report["directories"])
    lines.append(f"Showing {len(report['directories'])} of {report['matching_directories']} matching directories ({report['total_directories']} before threshold)")
    lines.extend(f"Warning: {w}" for w in report["warnings"])
    lines.append(report["path_policy"])
    return "\n".join(lines) + "\n"


def inventory_report(snapshot: dict[str, Any], *, group_by: str = "extension", depth: int = 1,
                     sort: str = "bytes", limit: int = 20) -> dict[str, Any]:
    import posixpath
    positive_count(depth, "depth")
    positive_count(limit, "limit")
    if group_by not in {"extension", "directory"} or sort not in {"bytes", "entries", "name"}:
        raise GitError("invalid inventory grouping or sort")
    if snapshot["truncated"]:
        raise GitError("inventory requires an untruncated tree snapshot")
    groups: dict[str, dict[str, Any]] = {}
    for item in snapshot["files"]:
        key = (posixpath.splitext(posixpath.basename(item["path"]))[1].casefold() or "(none)") if group_by == "extension" else ("/".join(item["path"].split("/")[:-1][:depth]) or ".")
        row = groups.setdefault(key, {"group": key, "entries": 0, "known_bytes": 0, "unknown_size_entries": 0, "modes": {}})
        row["entries"] += 1
        row["known_bytes"] += item["size"] or 0
        row["unknown_size_entries"] += int(item["size"] is None)
        row["modes"][item["mode"]] = row["modes"].get(item["mode"], 0) + 1
    metric = "known_bytes" if sort == "bytes" else sort
    rows = sorted(groups.values(), key=lambda row: (0 if sort == "name" else -row[metric], row["group"]))
    return {"repo": snapshot["repo"], "path": snapshot["path"], "requested_ref": snapshot["requested_ref"],
            "resolved_ref": snapshot["resolved_ref"], "group_by": group_by, "depth": depth, "sort": sort,
            "total_entries": snapshot["matching_files"], "known_bytes": snapshot["total_bytes"],
            "unknown_size_entries": snapshot["unknown_size_entries"], "total_groups": len(rows), "groups": rows[:limit],
            "interpretation": "committed Git object bytes, including symlink contents; not checkout disk usage"}


@safe_display
def render_inventory(report: dict[str, Any]) -> str:
    lines = [f"Tree inventory: {report['path']} at {report['resolved_ref'][:12]}", "Entries  Known bytes  Unknown sizes  Group"]
    lines.extend(f"{r['entries']:7}  {r['known_bytes']:11}  {r['unknown_size_entries']:13}  {r['group']}" for r in report["groups"])
    lines.append(f"Showing {len(report['groups'])} of {report['total_groups']} groups")
    lines.append(report["interpretation"])
    return "\n".join(lines) + "\n"


@safe_display
def render_divergence(report: dict[str, Any]) -> str:
    lines = [f"Revision relationship: {report['relationship']}", f"Shared commits: {report['shared_commits']}", "Side  Unique commits  Ref"]
    lines.extend(f"{r['side']}  {r['unique_commits']}  {r['ref']} ({r['resolved_ref'][:12]})" for r in report["sides"])
    lines.extend(f"Warning: {w}" for w in report["warnings"])
    return "\n".join(lines) + "\n"
