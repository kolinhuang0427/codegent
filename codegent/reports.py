"""Maintainer reports derived from observed repository history."""
from __future__ import annotations

from typing import Any

from .models import Bloodline
from .tracer import iso_date


def author_report(bloodline: Bloodline, *, sort: str = "commits", limit: int = 20) -> dict[str, Any]:
    authors: dict[str, dict[str, Any]] = {}
    for commit in bloodline.commits:
        row = authors.setdefault(commit.author, {
            "author": commit.author, "commits": 0, "additions": 0, "deletions": 0,
            "binary_changes": 0, "first_seen": commit.date, "last_seen": commit.date,
        })
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
    rows = sorted(authors.values(), key=lambda row: (
        0 if sort == "name" else -row[sort], row["author"].casefold(), row["author"],
    ))
    return {
        "path": bloodline.path, "repo": bloodline.repo, "requested_ref": bloodline.requested_ref,
        "history_complete": bloodline.history_complete, "warnings": bloodline.warnings,
        "selection": bloodline.selection, "total_commits": len(bloodline.commits),
        "total_authors": len(rows), "authors": rows[:limit], "sort": sort,
    }


def render_authors(report: dict[str, Any]) -> str:
    lines = [f"Authors: {report['path']}", "Commits  Churn  Author"]
    lines.extend(f"{row['commits']:7}  {row['churn']:5}  {row['author']}" for row in report["authors"])
    lines.extend(f"Warning: {warning}" for warning in report["warnings"])
    return "\n".join(lines) + "\n"


def hotspot_report(history: Bloodline, *, limit: int = 20, sort: str = "churn", min_commits: int = 1) -> dict[str, Any]:
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
    rows = sorted((row for row in files.values() if row["commits"] >= min_commits),
                  key=lambda row: (-row[sort], row["path"]))
    return {
        "repo": history.repo, "path": history.path, "requested_ref": history.requested_ref,
        "history_complete": history.history_complete, "warnings": history.warnings,
        "selection": history.selection, "scanned_commits": len(history.commits),
        "matching_files": len(rows), "files": rows[:limit], "sort": sort,
        "path_policy": "historical names are counted separately across renames",
    }


def render_hotspots(report: dict[str, Any]) -> str:
    lines = [f"Hotspots: {report['path']}", "Churn  Commits  Path"]
    lines.extend(f"{row['churn']:5}  {row['commits']:7}  {row['path']}" for row in report["files"])
    lines.extend(f"Warning: {warning}" for warning in report["warnings"])
    lines.append(report["path_policy"])
    return "\n".join(lines) + "\n"


def render_owners(report: dict[str, Any]) -> str:
    lines = [f"Line ownership: {report['path']} ({report['selected_lines']} lines)", "Lines  Percent  Author"]
    lines.extend(f"{row['lines']:5}  {row['percentage']:6.2f}%  {row['author']}" for row in report["owners"])
    lines.append(report["attribution"])
    return "\n".join(lines) + "\n"
