"""Git-backed history traversal for codegent."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from typing import Any

from .models import Bloodline, CommitNode


class GitError(RuntimeError):
    """Base error for git command failures."""


class GitRepositoryError(GitError):
    """Raised when a path is not a usable git repository."""


class GitExecutionError(GitError):
    """Raised when Git cannot be started."""


class PathNotFoundError(GitError):
    """Raised when a traced path has no history."""


@dataclass(slots=True)
class DiffLineage:
    repo: str
    commit_a: str
    commit_b: str
    files: list[dict[str, Any]]
    stat: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "commit_a": self.commit_a,
            "commit_b": self.commit_b,
            "files": self.files,
            "stat": self.stat,
        }


class GitTracer:
    """Trace file history through git using subprocess calls."""

    def __init__(self, repo: str = ".") -> None:
        self.repo = os.path.abspath(repo)

    def git(self, args: list[str], *, check: bool = True, text: bool = True) -> str:
        cmd = ["git", "-C", self.repo, *args]
        try:
            result = subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=text,
            )
        except OSError as exc:
            raise GitExecutionError(f"cannot run git: {exc.strerror or exc}") from exc
        if check and result.returncode != 0:
            stderr = result.stderr.strip() if isinstance(result.stderr, str) else ""
            raise GitError(stderr or f"git command failed: {' '.join(cmd)}")
        return result.stdout if isinstance(result.stdout, str) else result.stdout.decode()

    def ensure_repository(self) -> None:
        if not os.path.isdir(self.repo):
            raise GitRepositoryError(f"repository path does not exist: {self.repo}")
        try:
            inside = self.git(["rev-parse", "--is-inside-work-tree"]).strip()
        except GitExecutionError:
            raise
        except GitError as exc:
            raise GitRepositoryError(f"not a git repository: {self.repo}") from exc
        if inside != "true":
            raise GitRepositoryError(f"not a git repository: {self.repo}")

    def has_commits(self) -> bool:
        self.ensure_repository()
        return bool(self.git(["rev-parse", "--verify", "HEAD"], check=False).strip())

    def root(self) -> str:
        self.ensure_repository()
        return self.git(["rev-parse", "--show-toplevel"]).strip()

    def list_reachable_commits(self, ref: str = "HEAD", path: str | None = None) -> list[str]:
        args = ["rev-list", "--reverse", ref]
        if path:
            args.extend(["--", path])
        output = self.git(args)
        return [line for line in output.splitlines() if line]

    def trace_path(
        self,
        path: str,
        ref: str = "HEAD",
        *,
        max_commits: int | None = 10000,
    ) -> Bloodline:
        if max_commits is not None and max_commits <= 0:
            raise GitError("max_commits must be greater than zero or None")
        self.ensure_repository()
        if not self.has_commits():
            raise GitRepositoryError("repository has no commits yet")

        args = [
            "log",
            "--follow",
            "--date=iso-strict",
            "--format=%x1e%H%x1f%P%x1f%an%x1f%ae%x1f%ad%x1f%s",
            "--numstat",
            "--summary",
        ]
        if max_commits is not None and max_commits > 0:
            args.append(f"--max-count={max_commits}")
        args.extend([ref, "--", path])

        output = self.git(args)
        newest_first = self._parse_log(output)
        if not newest_first:
            raise PathNotFoundError(
                f"no history found for {path!r}; check the path or choose an older commit"
            )

        commits = list(reversed(newest_first))
        self._assign_roles(commits)
        return Bloodline(
            path=path,
            commits=commits,
            repo=self.root(),
            requested_ref=ref,
            followed_renames=True,
            max_commits=max_commits,
            truncated=max_commits is not None and len(commits) >= max_commits,
        )

    def diff_lineage(self, commit_a: str, commit_b: str) -> DiffLineage:
        self.ensure_repository()
        if not self.has_commits():
            raise GitRepositoryError("repository has no commits yet")
        stat = self.git(["diff", "--stat", "--find-renames", commit_a, commit_b])
        numstat = self.git(["diff", "--numstat", "--find-renames", commit_a, commit_b])
        name_status = self.git(["diff", "--name-status", "--find-renames", commit_a, commit_b])
        files = self._merge_diff_outputs(numstat, name_status)
        return DiffLineage(
            repo=self.root(),
            commit_a=commit_a,
            commit_b=commit_b,
            files=files,
            stat=stat.rstrip(),
        )

    def _parse_log(self, output: str) -> list[CommitNode]:
        commits: list[CommitNode] = []
        for raw_block in output.split("\x1e"):
            block = raw_block.strip("\n")
            if not block.strip():
                continue
            lines = block.splitlines()
            header = lines[0]
            parts = header.split("\x1f")
            if len(parts) < 6:
                continue
            commit_hash, parents, author_name, author_email, date, message = parts[:6]
            node = CommitNode(
                hash=commit_hash,
                parents=[parent for parent in parents.split() if parent],
                author_name=author_name,
                author_email=author_email,
                date=date,
                message=message,
            )
            rename_from: str | None = None
            for line in lines[1:]:
                stripped = line.strip()
                if not stripped:
                    continue
                if self._looks_like_numstat(line):
                    added, deleted, file_path, binary = self._parse_numstat(line)
                    node.additions += added
                    node.deletions += deleted
                    node.binary = node.binary or binary
                    if file_path and file_path not in node.files:
                        node.files.append(file_path)
                    continue
                if stripped.startswith("rename from "):
                    rename_from = stripped.removeprefix("rename from ").strip()
                    node.renamed_from = rename_from
                    continue
                if stripped.startswith("rename to "):
                    node.renamed_to = stripped.removeprefix("rename to ").strip()
                    if rename_from:
                        node.renamed_from = rename_from
                    continue
                match = re.match(r"rename\s+(.+?)\s+=>\s+(.+?)\s+\(\d+%\)", stripped)
                if match:
                    node.renamed_from = self._clean_rename_path(match.group(1))
                    node.renamed_to = self._clean_rename_path(match.group(2))
            commits.append(node)
        return commits

    def _looks_like_numstat(self, line: str) -> bool:
        parts = line.split("\t")
        if len(parts) < 3:
            return False
        return (parts[0].isdigit() or parts[0] == "-") and (
            parts[1].isdigit() or parts[1] == "-"
        )

    def _parse_numstat(self, line: str) -> tuple[int, int, str, bool]:
        parts = line.split("\t")
        added_raw, deleted_raw = parts[0], parts[1]
        file_path = "\t".join(parts[2:])
        binary = added_raw == "-" or deleted_raw == "-"
        added = 0 if binary else int(added_raw)
        deleted = 0 if binary else int(deleted_raw)
        return added, deleted, self._clean_rename_path(file_path), binary

    def _clean_rename_path(self, path: str) -> str:
        cleaned = path.strip()
        if " => " not in cleaned:
            return cleaned
        prefix = ""
        suffix = ""
        body = cleaned
        if "{" in cleaned and "}" in cleaned:
            prefix = cleaned.split("{", 1)[0]
            body = cleaned.split("{", 1)[1].rsplit("}", 1)[0]
            suffix = cleaned.rsplit("}", 1)[1]
        left, right = [part.strip() for part in body.split(" => ", 1)]
        return f"{prefix}{right}{suffix}"

    def _assign_roles(self, commits: list[CommitNode]) -> None:
        if not commits:
            return
        origin_author = commits[0].author
        heir_seen = False
        for index, commit in enumerate(commits):
            if index == 0:
                commit.role = "origin"
            elif commit.renamed_from or commit.renamed_to:
                commit.role = "renamed"
            elif commit.author != origin_author and not heir_seen:
                commit.role = "heir"
                heir_seen = True
            elif commit.author != origin_author:
                commit.role = "co-author"
            else:
                commit.role = "descendant"

    def _merge_diff_outputs(self, numstat: str, name_status: str) -> list[dict[str, Any]]:
        stats_by_path: dict[str, dict[str, Any]] = {}
        for line in numstat.splitlines():
            if not self._looks_like_numstat(line):
                continue
            added, deleted, path, binary = self._parse_numstat(line)
            stats_by_path[path] = {
                "path": path,
                "additions": added,
                "deletions": deleted,
                "binary": binary,
                "status": "modified",
            }

        for line in name_status.splitlines():
            parts = line.split("\t")
            if not parts:
                continue
            status = parts[0]
            if status.startswith("R") and len(parts) >= 3:
                path = parts[2]
                entry = stats_by_path.setdefault(
                    path,
                    {"path": path, "additions": 0, "deletions": 0, "binary": False},
                )
                entry["status"] = "renamed"
                entry["renamed_from"] = parts[1]
                entry["renamed_to"] = parts[2]
            elif len(parts) >= 2:
                path = parts[1]
                entry = stats_by_path.setdefault(
                    path,
                    {"path": path, "additions": 0, "deletions": 0, "binary": False},
                )
                entry["status"] = self._status_name(status)
        return list(stats_by_path.values())

    def _status_name(self, status: str) -> str:
        return {
            "A": "added",
            "M": "modified",
            "D": "deleted",
            "C": "copied",
            "T": "type-changed",
        }.get(status[:1], status.lower())
