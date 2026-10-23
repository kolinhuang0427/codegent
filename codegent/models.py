"""Data models for code genealogy results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _parse_git_date(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


@dataclass(slots=True)
class CommitNode:
    """A commit that touched a traced path."""

    hash: str
    parents: list[str]
    author_name: str
    author_email: str
    date: str
    message: str
    additions: int = 0
    deletions: int = 0
    files: list[str] = field(default_factory=list)
    binary: bool = False
    changes: list[dict[str, Any]] = field(default_factory=list)
    renamed_from: str | None = None
    renamed_to: str | None = None
    role: str = "descendant"

    @property
    def short_hash(self) -> str:
        return self.hash[:7]

    @property
    def author(self) -> str:
        if self.author_email:
            return f"{self.author_name} <{self.author_email}>"
        return self.author_name

    def to_dict(self) -> dict[str, Any]:
        return {
            "hash": self.hash,
            "short_hash": self.short_hash,
            "parents": self.parents,
            "author_name": self.author_name,
            "author_email": self.author_email,
            "date": self.date,
            "message": self.message,
            "additions": self.additions,
            "deletions": self.deletions,
            "files": self.files,
            "changes": self.changes,
            "binary": self.binary,
            "renamed_from": self.renamed_from,
            "renamed_to": self.renamed_to,
            "role": self.role,
        }


@dataclass(slots=True)
class CodeGene:
    """A compact lineage entry used by ancestry reports."""

    commit_hash: str
    short_hash: str
    path: str
    author: str
    date: str
    role: str
    lines_added: int
    lines_deleted: int
    carried_lines: int
    binary: bool = False
    migrated_from: str | None = None
    migrated_to: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "commit_hash": self.commit_hash,
            "short_hash": self.short_hash,
            "path": self.path,
            "author": self.author,
            "date": self.date,
            "role": self.role,
            "lines_added": self.lines_added,
            "lines_deleted": self.lines_deleted,
            "carried_lines": self.carried_lines,
            "binary": self.binary,
            "migrated_from": self.migrated_from,
            "migrated_to": self.migrated_to,
        }


@dataclass(slots=True)
class Bloodline:
    """The complete traced history for a path."""

    path: str
    commits: list[CommitNode]
    repo: str
    requested_ref: str = "HEAD"
    followed_renames: bool = True
    max_commits: int | None = None
    truncated: bool = False
    shallow: bool = False
    mailmap: bool = False
    rename_threshold: int = 50
    selection: dict[str, Any] = field(default_factory=dict)

    @property
    def history_complete(self) -> bool:
        return not (self.truncated or self.shallow or self.selection)

    @property
    def warnings(self) -> list[str]:
        warnings: list[str] = []
        if self.truncated:
            warnings.append(f"History truncated at --max-commits={self.max_commits}.")
        if self.shallow:
            warnings.append("Shallow repository: older history may be missing.")
        if self.selection:
            warnings.append("History selection is active; statistics describe selected commits.")
        if not self.history_complete:
            warnings.append("The earliest observed commit is not a confirmed file origin.")
        return warnings

    @property
    def origin(self) -> CommitNode | None:
        return self.commits[0] if self.commits else None

    @property
    def latest(self) -> CommitNode | None:
        return self.commits[-1] if self.commits else None

    @property
    def authors(self) -> list[str]:
        seen: set[str] = set()
        authors: list[str] = []
        for commit in self.commits:
            if commit.author not in seen:
                seen.add(commit.author)
                authors.append(commit.author)
        return authors

    @property
    def migrations(self) -> list[tuple[str, str]]:
        moves: list[tuple[str, str]] = []
        for commit in self.commits:
            if commit.renamed_from and commit.renamed_to:
                moves.append((commit.renamed_from, commit.renamed_to))
        return moves

    @property
    def total_additions(self) -> int:
        return sum(commit.additions for commit in self.commits)

    @property
    def total_deletions(self) -> int:
        return sum(commit.deletions for commit in self.commits)

    @property
    def current_carried_lines(self) -> int:
        carried = 0
        for commit in self.commits:
            carried += commit.additions - commit.deletions
            if carried < 0:
                carried = 0
        return carried

    @property
    def age_days(self) -> int | None:
        origin = self.origin
        if not origin:
            return None
        parsed = _parse_git_date(origin.date)
        if not parsed:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - parsed).days)

    @property
    def genetic_diversity(self) -> int:
        return len(self.authors)

    def genes(self) -> list[CodeGene]:
        carried = 0
        genes: list[CodeGene] = []
        current_path = self.path
        for commit in reversed(self.commits):
            if commit.renamed_from:
                current_path = commit.renamed_from
        for commit in self.commits:
            if commit.renamed_to:
                current_path = commit.renamed_to
            carried += commit.additions - commit.deletions
            if carried < 0:
                carried = 0
            genes.append(
                CodeGene(
                    commit_hash=commit.hash,
                    short_hash=commit.short_hash,
                    path=current_path,
                    author=commit.author,
                    date=commit.date,
                    role=commit.role,
                    lines_added=commit.additions,
                    lines_deleted=commit.deletions,
                    carried_lines=carried,
                    binary=commit.binary,
                    migrated_from=commit.renamed_from,
                    migrated_to=commit.renamed_to,
                )
            )
        return genes

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "repo": self.repo,
            "requested_ref": self.requested_ref,
            "followed_renames": self.followed_renames,
            "max_commits": self.max_commits,
            "truncated": self.truncated,
            "shallow": self.shallow,
            "mailmap": self.mailmap,
            "rename_threshold": self.rename_threshold,
            "history_complete": self.history_complete,
            "origin_confirmed": self.history_complete and self.origin is not None,
            "selection": self.selection,
            "warnings": self.warnings,
            "origin": self.origin.to_dict() if self.origin else None,
            "latest": self.latest.to_dict() if self.latest else None,
            "total_commits": len(self.commits),
            "authors": self.authors,
            "genetic_diversity": self.genetic_diversity,
            "migrations": self.migrations,
            "age_days": self.age_days,
            "current_carried_lines": self.current_carried_lines,
            "total_additions": self.total_additions,
            "total_deletions": self.total_deletions,
            "commits": [commit.to_dict() for commit in self.commits],
            "genes": [gene.to_dict() for gene in self.genes()],
        }
