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
