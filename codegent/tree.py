"""Text renderers for code genealogy reports."""

from __future__ import annotations

import textwrap

from .colors import ANSI, heading, muted, paint, role
from .models import Bloodline, CommitNode
from .tracer import DiffLineage


def render_trace(bloodline: Bloodline, *, color: bool = True) -> str:
    lines = [
        "",
        f"  {heading('Tracing lineage for:', color)} {bloodline.path}",
        f"  {muted('Follows renames:', color)} {'yes' if bloodline.followed_renames else 'no'}",
        "",
        render_family_tree(bloodline, color=color),
        "",
        render_bloodline_summary(bloodline, color=color),
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_family_tree(bloodline: Bloodline, *, color: bool = True) -> str:
    if not bloodline.commits:
        return "  No lineage found."
    rendered: list[str] = []
    for index, commit in enumerate(bloodline.commits):
        rendered.extend(_commit_box(commit, color=color))
        if index < len(bloodline.commits) - 1:
            rendered.append("          │")
            rendered.append("          ▼")
    return "\n".join(f"  {line}" for line in rendered)


def render_ancestry(bloodline: Bloodline, *, color: bool = True) -> str:
    lines = [
        "",
        f"  {heading('Ancestry:', color)} {bloodline.path}",
        "",
    ]
    lines.extend(f"  Warning: {warning}" for warning in bloodline.warnings)
    genes = bloodline.genes()
    for index, gene in enumerate(genes):
        prefix = "└─" if index == len(genes) - 1 else "├─"
        moved = ""
        if gene.migrated_from and gene.migrated_to:
            moved = f"  {muted(gene.migrated_from + ' -> ' + gene.migrated_to, color)}"
        binary = " binary" if gene.binary else ""
        lines.append(
            "  "
            + f"{prefix} {paint(gene.short_hash, ANSI.YELLOW, color)} "
            + f"{role(gene.role, color)} "
            + f"{gene.author}  {muted(gene.date, color)}"
        )
        lines.append(
            "  "
            + f"   carried={gene.carried_lines} +{gene.lines_added} -{gene.lines_deleted}{binary}{moved}"
        )
    return "\n".join(lines).rstrip() + "\n"


def render_genemap(bloodline: Bloodline, *, color: bool = True) -> str:
    lines = [
        "",
        f"  {heading('Gene Map:', color)} {bloodline.path}",
        f"  {muted('oldest', color)}",
    ]
    lines.extend(f"  Warning: {warning}" for warning in bloodline.warnings)
    for commit in bloodline.commits:
        marker = _role_marker(commit.role)
        marker = paint(marker, _role_color(commit.role), color, bold=True)
        annotation = _milestone(commit)
        lines.append(
            "  "
            + f"│ {marker} {paint(commit.short_hash, ANSI.YELLOW, color)} "
            + f"{_truncate(commit.message, 54)}"
        )
        detail = f"{commit.author_name}  +{commit.additions} -{commit.deletions}"
        if commit.binary:
            detail += "  binary"
        if annotation:
            detail += f"  {annotation}"
        lines.append("  " + f"│   {muted(detail, color)}")
    lines.append(f"  {muted('newest', color)}")
    return "\n".join(lines).rstrip() + "\n"


def render_bloodline_summary(bloodline: Bloodline, *, color: bool = True) -> str:
    origin = bloodline.origin
    if origin is None:
        return "  No bloodline available."
    age = _format_age_days(bloodline.age_days)
    origin_label = "Origin" if bloodline.history_complete else "Earliest observed"
    migrations = len(bloodline.migrations)
    migration_word = "event" if migrations == 1 else "events"
    lines = [
        f"  {heading('Bloodline Summary', color)}",
        "  ─────────────────────────",
        f"  {origin_label} author: {origin.author}",
        f"  {origin_label} commit: {paint(origin.short_hash, ANSI.YELLOW, color)}",
        f"  {origin_label} date: {origin.date}",
        f"  Code age:           {age}",
        f"  Total commits:      {len(bloodline.commits)}",
        f"  Migration events:   {migrations} {migration_word}",
        f"  Genetic diversity:  {bloodline.genetic_diversity} authors",
        f"  Current line trace: {bloodline.current_carried_lines} net lines",
    ]
    lines.extend(f"  Warning: {warning}" for warning in bloodline.warnings)
    if bloodline.latest and bloodline.latest.binary:
        lines.append("  Binary note:        latest traced change was binary")
    return "\n".join(lines)


def render_diff_lineage(diff: DiffLineage, *, color: bool = True) -> str:
    lines = [
        "",
        f"  {heading('Diff Lineage:', color)} {diff.commit_a} -> {diff.commit_b}",
        "",
    ]
    if not diff.files:
        lines.append("  No file-level changes found.")
    for item in diff.files:
        path = item["path"]
        status = item.get("status", "modified")
        binary = " binary" if item.get("binary") else ""
        moved = ""
        if status == "renamed":
            moved = f" ({item.get('renamed_from')} -> {item.get('renamed_to')})"
        lines.append(
            "  "
            + f"├─ {role(status, color)} {path}{moved} "
            + f"+{item.get('additions', 0)} -{item.get('deletions', 0)}{binary}"
        )
    if diff.stat:
        lines.append("")
        lines.append(textwrap.indent(diff.stat, "  "))
    return "\n".join(lines).rstrip() + "\n"


def _commit_box(commit: CommitNode, *, color: bool) -> list[str]:
    width = 74
    title = f"Commit {commit.short_hash} - {_truncate(commit.message, 48)}"
    detail_lines = [
        title,
        f"Author: {commit.author}",
        f"Date:   {commit.date}",
        f"Role:   {commit.role.upper()}",
    ]
    if commit.binary:
        detail_lines.append("Stats:  binary file change")
    else:
        detail_lines.append(f"Stats:  +{commit.additions} -{commit.deletions} lines")
    if commit.renamed_from or commit.renamed_to:
        detail_lines.append(f"Rename: {commit.renamed_from or '?'} -> {commit.renamed_to or '?'}")

    lines = ["╭" + "─" * width + "╮"]
    for index, line in enumerate(detail_lines):
        content = line
        if index == 0:
            content = paint(line, ANSI.YELLOW, color, bold=True)
        elif line.startswith("Role:"):
            content = "Role:   " + role(commit.role.upper(), color)
        visible = _visible_len(line)
        lines.append("│ " + content + " " * max(0, width - visible - 1) + "│")
    lines.append("╰" + "─" * width + "╯")
    return lines


def _visible_len(text: str) -> int:
    return len(text)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _format_age_days(days: int | None) -> str:
    if days is None:
        return "unknown"
    if days < 60:
        return f"{days} days"
    if days < 730:
        months = max(1, days // 30)
        return f"{months} months"
    years = days / 365.2425
    return f"{years:.1f} years"


def _role_marker(role_name: str) -> str:
    return {
        "origin": "◆",
        "heir": "◇",
        "co-author": "●",
        "renamed": "↷",
        "descendant": "•",
    }.get(role_name, "•")


def _role_color(role_name: str) -> str:
    return {
        "origin": ANSI.GREEN,
        "heir": ANSI.CYAN,
        "co-author": ANSI.MAGENTA,
        "renamed": ANSI.YELLOW,
        "descendant": ANSI.WHITE,
    }.get(role_name, ANSI.WHITE)


def _milestone(commit: CommitNode) -> str:
    if commit.renamed_from or commit.renamed_to:
        return f"rename {commit.renamed_from or '?'} -> {commit.renamed_to or '?'}"
    total = commit.additions + commit.deletions
    if commit.binary:
        return "binary"
    if total >= 500:
        return "major rewrite"
    if commit.deletions > commit.additions * 2 and commit.deletions > 50:
        return "large pruning"
    if commit.additions > commit.deletions * 2 and commit.additions > 50:
        return "large growth"
    return ""
