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
    for label, key in (("Repository", "repo"), ("Path", "path"), ("Ref", "requested_ref"),
                       ("Base", "commit_a"), ("Target", "commit_b")):
        if key in report:
            lines.append(f"**{label}:** {_cell(report[key])}")
    lines.append("")
    lines.extend(f"> Warning: {_cell(warning)}" for warning in report.get("warnings", []))
    lines.append("")
    if command == "authors":
        lines += _table(["Author", "Commits", "Additions", "Deletions", "Churn"], [
            [row[key] for key in ("author", "commits", "additions", "deletions", "churn")]
            for row in report["authors"]])
    elif command == "hotspots":
        lines += _table(["Path", "Commits", "Churn", "Binary changes"], [
            [row[key] for key in ("path", "commits", "churn", "binary_changes")]
            for row in report["files"]])
        lines += ["", _cell(report["path_policy"])]
    elif command == "owners":
        lines += _table(["Author", "Lines", "Percent"], [
            [row[key] for key in ("author", "lines", "percentage")] for row in report["owners"]])
        lines += ["", _cell(report["attribution"])]
    elif command == "diff":
        summary = report["summary"]
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
