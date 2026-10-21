"""Git-backed history traversal for codegent."""

from __future__ import annotations

import os
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
        self.repo = os.path.realpath(os.path.expanduser(repo))
        self.path_base = self.repo

    def git(self, args: list[str], *, check: bool = True, text: bool = True) -> str:
        cmd = ["git", "--literal-pathspecs", "-C", self.repo, *args]
        try:
            result = subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
            )
        except OSError as exc:
            raise GitExecutionError(f"cannot run git: {exc.strerror or exc}") from exc
        if check and result.returncode != 0:
            stderr = result.stderr.decode("utf-8", "replace").strip()
            raise GitError(stderr or f"git command failed: {' '.join(cmd)}")
        return result.stdout.decode("utf-8", "surrogateescape")

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
        self.repo = self.git(["rev-parse", "--show-toplevel"]).rstrip("\n")

    def has_commits(self) -> bool:
        self.ensure_repository()
        return bool(self.git(["rev-parse", "--verify", "HEAD"], check=False).strip())

    def root(self) -> str:
        self.ensure_repository()
        return self.repo

    def normalize_path(self, path: str) -> str:
        self.ensure_repository()
        absolute = os.path.abspath(os.path.join(self.path_base, path))
        absolute = os.path.join(os.path.realpath(os.path.dirname(absolute)), os.path.basename(absolute))
        if os.path.commonpath([self.repo, absolute]) != self.repo:
            raise GitError(f"path is outside the repository: {path!r}")
        return os.path.relpath(absolute, self.repo).replace(os.sep, "/")

    def list_reachable_commits(self, ref: str = "HEAD", path: str | None = None) -> list[str]:
        args = ["rev-list", "--reverse", self.resolve_ref(ref)]
        if path:
            args.extend(["--", path])
        output = self.git(args)
        return [line for line in output.splitlines() if line]

    def resolve_ref(self, ref: str) -> str:
        """Accept a single commit-ish, never a revision range or Git option."""
        try:
            return self.git([
                "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}",
            ]).strip()
        except GitExecutionError:
            raise
        except GitError as exc:
            raise GitError(f"invalid commit/ref: {ref!r}") from exc

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

        path = self.normalize_path(path)

        args = [
            "log",
            "--follow",
            "--date=iso-strict",
            "--format=%x00%H%x00%P%x00%an%x00%ae%x00%aI%x00%s",
            "-z",
            "--no-ext-diff",
            "--no-textconv",
            "--numstat",
            "--find-renames",
        ]
        if max_commits is not None and max_commits > 0:
            args.append(f"--max-count={max_commits + 1}")
        args.extend([self.resolve_ref(ref), "--", path])

        output = self.git(args)
        newest_first = self._parse_log(output)
        truncated = max_commits is not None and len(newest_first) > max_commits
        if truncated:
            newest_first = newest_first[:max_commits]
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
            truncated=truncated,
        )

    def diff_lineage(self, commit_a: str, commit_b: str) -> DiffLineage:
        self.ensure_repository()
        if not self.has_commits():
            raise GitRepositoryError("repository has no commits yet")
        base, target = self.resolve_ref(commit_a), self.resolve_ref(commit_b)
        stat = self.git(["diff", "--no-ext-diff", "--no-textconv", "--stat", "--find-renames", base, target, "--"])
        numstat = self.git(["diff", "--no-ext-diff", "--no-textconv", "--numstat", "-z", "--find-renames", base, target, "--"])
        name_status = self.git(["diff", "--no-ext-diff", "--no-textconv", "--name-status", "-z", "--find-renames", base, target, "--"])
        files = self._merge_diff_outputs(numstat, name_status)
        return DiffLineage(
            repo=self.root(),
            commit_a=commit_a,
            commit_b=commit_b,
            files=files,
            stat=stat.rstrip(),
        )

    def _numstat_entry(self, tokens: list[str], index: int) -> tuple[dict[str, Any], int]:
        record = tokens[index].removeprefix("\n")
        added, deleted, path = record.split("\t", 2)
        binary = added == "-" or deleted == "-"
        item: dict[str, Any] = {
            "path": path, "additions": 0 if binary else int(added),
            "deletions": 0 if binary else int(deleted), "binary": binary,
        }
        index += 1
        if not path:
            old, new = tokens[index:index + 2]
            item.update(path=new, renamed_from=old, renamed_to=new)
            index += 2
        return item, index

    def _parse_log(self, output: str) -> list[CommitNode]:
        # NUL delimiters preserve whitespace, Unicode and control characters in paths.
        tokens = output.split("\0")
        commits: list[CommitNode] = []
        index = 0
        while index < len(tokens):
            if tokens[index] in ("", "\n"):
                index += 1
                continue
            commit_hash, parents, author_name, author_email, date, message = tokens[index:index + 6]
            index += 6
            node = CommitNode(
                hash=commit_hash, parents=parents.split(), author_name=author_name,
                author_email=author_email, date=date, message=message,
            )
            while index < len(tokens) and tokens[index] not in ("", "\n"):
                item, index = self._numstat_entry(tokens, index)
                node.additions += item["additions"]
                node.deletions += item["deletions"]
                node.binary = node.binary or item["binary"]
                node.files.append(item["path"])
                if "renamed_from" in item:
                    node.renamed_from = item["renamed_from"]
                    node.renamed_to = item["renamed_to"]
            commits.append(node)
        return commits

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
        tokens = numstat.split("\0")
        index = 0
        while index < len(tokens) and tokens[index]:
            item, index = self._numstat_entry(tokens, index)
            item["status"] = "modified"
            stats_by_path[item["path"]] = item

        tokens = name_status.split("\0")
        index = 0
        while index < len(tokens) and tokens[index]:
            status, path = tokens[index:index + 2]
            index += 2
            old_path = None
            if status.startswith(("R", "C")):
                old_path, path = path, tokens[index]
                index += 1
            entry = stats_by_path.setdefault(path, {
                "path": path, "additions": 0, "deletions": 0, "binary": False,
            })
            entry["status"] = self._status_name(status)
            if old_path is not None:
                entry["renamed_from"] = old_path
                entry["renamed_to"] = path
        return list(stats_by_path.values())

    def _status_name(self, status: str) -> str:
        return {
            "A": "added",
            "M": "modified",
            "D": "deleted",
            "R": "renamed",
            "C": "copied",
            "T": "type-changed",
        }.get(status[:1], status.lower())
