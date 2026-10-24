"""Portable Markdown exports of structured reports."""
from __future__ import annotations

import html
import re
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
    elif command == "bloodline":
        origin = report.get("origin") or {}
        lines += _table(["Metric", "Value"], [
            ["Origin confirmed", report["origin_confirmed"]], ["Earliest observed commit", origin.get("hash", "none")],
            ["Earliest observed author", f"{origin.get('author_name', '')} <{origin.get('author_email', '')}>"],
            ["Age in days", report["age_days"] if report["age_days"] is not None else "unknown"],
            ["Total commits", report["total_commits"]], ["Migration events", len(report["migrations"])],
            ["Genetic diversity", report["genetic_diversity"]],
            ["Current net line trace", report["current_carried_lines"] if report["current_carried_lines"] is not None else "unknown"],
        ])
    elif command == "hotspots":
        lines += _table(["Path", "Commits", "Authors", "Churn", "Last changed", "Binary changes"], [
            [row[key] for key in ("path", "commits", "authors", "churn", "last_changed", "binary_changes")]
            for row in report["files"]])
        lines += ["", f"Showing {len(report['files'])} of {report['matching_files']} matching paths.",
                  _cell(report["path_policy"])]
    elif command == "divergence":
        lines += [f"Relationship: {_cell(report['relationship'])}; shared commits: {report['shared_commits']}.", ""]
        lines += _table(["Side", "Ref", "Resolved tip", "Unique commits"], [
            [row[key] for key in ("side", "ref", "resolved_ref", "unique_commits")] for row in report["sides"]])
    elif command == "inventory":
        lines += [f"Entries: {report['total_entries']} selected of {report['unfiltered_entries']} before filters; filters: {_cell(report['filters'])}.", ""]
        lines += _table(["Group", "Entries", "Known bytes", "Largest known bytes", "Unknown sizes"], [
            [row[key] for key in ("group", "entries", "known_bytes", "largest_known_bytes", "unknown_size_entries")] for row in report["groups"]])
        lines += ["", f"Showing {len(report['groups'])} of {report['total_groups']} groups.", _cell(report["interpretation"])]
    elif command == "directories":
        lines += _table(["Directory", "Commits", "Authors", "Files", "Churn"], [
            [row[key] for key in ("path", "commits", "authors", "files", "churn")] for row in report["directories"]])
        lines += ["", f"Showing {len(report['directories'])} of {report['matching_directories']} matching directories ({report['total_directories']} before threshold).", _cell(report["path_policy"])]
    elif command == "owners":
        lines += [f"Selected lines: {report['selected_lines']} of {report['file_lines']}; range: {_cell(report['line_range'] or 'whole file')}.", ""]
        keys = ["author", "lines", "percentage"] + (["commit"] if report["group_by"] == "commit" else [])
        if report.get("show_lines"):
            keys.append("line_ranges")
        lines += _table(["Author", "Lines", "Percent"] + (["Commit"] if "commit" in keys else []) + (["Line ranges"] if "line_ranges" in keys else []), [
            [row[key] for key in keys] for row in report["owners"]])
        lines += ["", f"Showing {report['displayed_groups']} of {report['total_groups']} groups; omitted lines: {report['omitted_lines']}.", _cell(report["attribution"])]
    elif command == "patch":
        preview = "\n".join(escape_text(line) for line in report["patch"].split("\n"))
        longest = max((len(match.group()) for match in re.finditer(r"`+", preview)), default=0)
        fence = "`" * max(3, longest + 1)
        lines += [fence + "diff", preview.rstrip("\n"), fence]
    elif command == "refs":
        lines += _table(["Ref", "Kind", "Object type", "Object ID", "Peeled ID"], [
            [row[key] for key in ("ref", "kind", "object_type", "object_id", "peeled_object_id")] for row in report["refs"]])
        lines += ["", f"Showing {len(report['refs'])} of {report['total_refs']} references."]
    elif command == "doctor":
        lines += _table(["Check", "Value"], [[key, value] for key, value in report.items()])
    elif command == "source":
        lines += _table(["Line", "Text"], [[row["number"], row["text"]] for row in report["lines"]])
    elif command == "files":
        lines += _table(["Path", "Mode", "Type", "Bytes", "Object ID"], [
            [row[key] for key in ("path", "mode", "type", "size", "object_id")] for row in report["files"]])
        lines += ["", f"Showing {len(report['files'])} of {report['matching_files']} matching entries ({report['total_files']} before filters)."]
    elif command == "cochange":
        lines += _table(["Path", "Shared commits", "Fraction", "Jaccard"], [
            [row[key] for key in ("path", "shared_commits", "fraction", "jaccard")] for row in report["files"]])
        lines += ["", f"Target commits: {report['target_commits']}; showing {len(report['files'])} "
                  f"of {report['matching_files']} matching paths.", _cell(report["interpretation"])]
    elif command == "timeline":
        keys = ["period", "commits", "authors", "files", "additions", "deletions", "binary_changes"]
        headers = ["Period", "Commits", "Authors", "Files", "+", "-", "Binary changes"]
        if report["cumulative"]:
            keys += ["cumulative_commits", "cumulative_additions", "cumulative_deletions", "cumulative_binary_changes"]
            headers += ["Total commits", "Total +", "Total -", "Total binary changes"]
        lines += _table(headers, [[row[key] for key in keys] for row in report["periods"]])
        if report["cumulative"]:
            lines += ["", _cell(report["cumulative_scope"])]
        lines += ["", _cell(report["date_basis"])]
    elif command == "diff":
        summary = report["summary"]
        lines += [f"Selected changes: {summary['files']} of {report['total_changed_files']}; "
                  f"statuses: {_cell(', '.join(report['statuses']) or 'all')}.", ""]
        lines += _table(["Files", "Additions", "Deletions", "Binary files"], [
            [summary[key] for key in ("files", "additions", "deletions", "binary_files")]])
        lines += [""] + _table(["Status", "Files"], [[key, count] for key, count in sorted(summary["statuses"].items())])
        if "files" in report:
            lines += [""] + _table(["Path", "Source path", "Status", "Binary", "Additions", "Deletions"], [
                [row["path"], row.get("renamed_from", row.get("copied_from", "-")), row["status"], row["binary"],
                 "unavailable" if row["binary"] else row["additions"], "unavailable" if row["binary"] else row["deletions"]]
                for row in report["files"]])
    else:
        lines += _table(["Commit", "Author", "Date", "Role", "+", "-", "Subject"], [
            [row[key] for key in ("short_hash", "author_name", "date", "role", "additions", "deletions", "message")]
            for row in report["commits"]])
    return "\n".join(lines).rstrip() + "\n"


# Schemas retain meaningful headers even when a report has no data rows.
_CSV_TABLES = {
    "divergence": ("sides", ("side", "ref", "resolved_ref", "unique_commits")),
    "inventory": ("groups", ("group", "entries", "known_bytes", "largest_known_bytes", "unknown_size_entries", "modes")),
    "directories": ("directories", ("path", "commits", "authors", "files", "additions", "deletions", "churn", "binary_changes")),
    "authors": ("authors", ("author", "commits", "additions", "deletions", "churn")),
    "hotspots": ("files", ("path", "commits", "authors", "churn", "binary_changes", "first_changed", "last_changed")),
    "cochange": ("files", ("path", "shared_commits", "fraction", "candidate_commits", "jaccard")),
    "files": ("files", ("path", "mode", "type", "size", "object_id")),
    "refs": ("refs", ("ref", "kind", "object_type", "object_id", "peeled_object_id", "peeled_type")),
    "owners": ("owners", ("author", "lines", "percentage", "boundary_lines", "commits", "commit")),
    "timeline": ("periods", ("period", "commits", "authors", "files", "additions", "deletions", "binary_changes")),
    "source": ("lines", ("number", "text")),
    "diff": ("files", ("path", "status", "additions", "deletions", "binary")),
}


def render_csv(report: dict[str, Any], command: str, *, delimiter: str = ",") -> str:
    """Export rows without losing the report's scope, evidence, or empty state.

    Nested values use JSON cells; null is JSON null, distinguishable from empty
    text. Metadata repeats on each row, or on a sentinel row for an empty table.
    """
    import csv
    import io
    import json

    if delimiter not in {",", ";", "\t"}:
        raise ValueError("CSV delimiter must be comma, semicolon, or tab")
    metadata = dict(report)
    if command == "doctor":
        rows = [{"check": key, "value": value} for key, value in report.items()]
        columns = ["check", "value"]
        metadata = {}
    elif command == "patch":
        rows = [{"patch": metadata.pop("patch")}]
        columns = ["patch"]
    elif command == "diff" and "files" not in report:
        rows = [metadata.pop("summary")]
        columns = ["files", "additions", "deletions", "binary_files", "statuses"]
    else:
        key, schema = _CSV_TABLES.get(command, ("commits", ("hash", "author_name", "author_email", "date", "committer_date", "message", "additions", "deletions", "role")))
        rows = metadata.pop(key)
        columns = list(schema)
    if command == "timeline" and report.get("cumulative"):
        columns += ["cumulative_" + key for key in ("commits", "additions", "deletions", "binary_changes")]
    columns.extend(sorted({key for row in rows for key in row} - set(columns)))
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(["row_present", *columns, "report_metadata"])
    encoded_metadata = json.dumps(metadata, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    def cell(value: Any) -> Any:
        return value if isinstance(value, (str, int, float)) and not isinstance(value, bool) else json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    for row in rows:
        writer.writerow(["true", *(cell(row.get(key)) for key in columns), encoded_metadata])
    if not rows:
        writer.writerow(["false", *("" for _ in columns), encoded_metadata])
    return output.getvalue()
