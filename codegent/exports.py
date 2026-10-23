"""Portable Markdown exports of structured reports."""
from __future__ import annotations

import html
from .display import escape_text
from typing import Any


def _cell(value: Any) -> str:
    return html.escape(escape_text(str(value)), quote=False).replace("\\", "\\\\").replace("|", "\\|").replace("`", "&#96;").replace("\n", "\\n").replace("\r", "\\r")


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    return ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(_cell(value) for value in row) + " |" for row in rows)]


def render_markdown(report: dict[str, Any], command: str) -> str:
    lines = [f"# codegent {command}", ""]
    for label, key in (("Repository", "repo"), ("Path", "path"), ("Ref", "requested_ref"), ("Resolved tip", "resolved_ref"),
                       ("Base", "commit_a"), ("Target", "commit_b"), ("Effective base", "resolved_a"), ("Effective target", "resolved_b")):
        if key in report:
            lines.append(f"**{label}:** {_cell(report[key])}")
    lines.append("")
    lines.extend(f"> Warning: {_cell(warning)}" for warning in report.get("warnings", []))
    lines.append("")
    if command == "authors":
        lines += _table(["Author", "Commits", "Additions", "Deletions", "Churn"], [
            [row[key] for key in ("author", "commits", "additions", "deletions", "churn")]
            for row in report["authors"]])
        lines += ["", f"Showing {report['displayed_authors']} of {report['total_authors']} author groups; "
                  f"matching: {report['matching_authors']}; omitted: {report['omitted_authors']}.",
                  f"Grouping: {_cell(report['group_by'])}; minimum commits: {report['min_commits']}."]
    elif command == "hotspots":
        lines += _table(["Path", "Commits", "Churn", "Binary changes"], [
            [row[key] for key in ("path", "commits", "churn", "binary_changes")]
            for row in report["files"]])
        lines += ["", f"Showing {len(report['files'])} of {report['matching_files']} matching paths.",
                  _cell(report["path_policy"])]
    elif command == "owners":
        lines += _table(["Author", "Lines", "Percent"], [
            [row[key] for key in ("author", "lines", "percentage")] for row in report["owners"]])
        lines += ["", _cell(report["attribution"])]
    elif command == "doctor":
        lines += _table(["Check", "Value"], [[key, value] for key, value in report.items()])
    elif command == "source":
        lines += _table(["Line", "Text"], [[row["number"], row["text"]] for row in report["lines"]])
    elif command == "files":
        lines += _table(["Path", "Mode", "Type", "Bytes", "Object ID"], [
            [row[key] for key in ("path", "mode", "type", "size", "object_id")] for row in report["files"]])
        lines += ["", f"Showing {len(report['files'])} of {report['total_files']} entries."]
    elif command == "cochange":
        lines += _table(["Path", "Shared commits", "Fraction"], [
            [row[key] for key in ("path", "shared_commits", "fraction")] for row in report["files"]])
        lines += ["", f"Target commits: {report['target_commits']}; showing {len(report['files'])} "
                  f"of {report['matching_files']} matching paths.", _cell(report["interpretation"])]
    elif command == "timeline":
        lines += _table(["Period", "Commits", "Authors", "Files", "+", "-"], [
            [row[key] for key in ("period", "commits", "authors", "files", "additions", "deletions")]
            for row in report["periods"]])
        lines += ["", _cell(report["date_basis"])]
    elif command == "diff":
        summary = report["summary"]
        lines += [f"Selected changes: {summary['files']} of {report['total_changed_files']}; "
                  f"statuses: {_cell(', '.join(report['statuses']) or 'all')}.", ""]
        lines += _table(["Files", "Additions", "Deletions", "Binary files"], [
            [summary[key] for key in ("files", "additions", "deletions", "binary_files")]])
        if "files" in report:
            lines += [""] + _table(["Path", "Status", "Additions", "Deletions"], [
                [row[key] for key in ("path", "status", "additions", "deletions")]
                for row in report["files"]])
    else:
        lines += _table(["Commit", "Author", "Date", "Role", "+", "-", "Subject"], [
            [row[key] for key in ("short_hash", "author_name", "date", "role", "additions", "deletions", "message")]
            for row in report["commits"]])
    return "\n".join(lines).rstrip() + "\n"
