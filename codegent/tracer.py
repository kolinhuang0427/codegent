"""Git-backed history traversal for codegent."""

from __future__ import annotations

import os
import math
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
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


def iso_date(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GitError(f"invalid ISO date: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


@dataclass(slots=True)
class DiffLineage:
    repo: str
    commit_a: str
    commit_b: str
    files: list[dict[str, Any]]
    stat: str
    rename_threshold: int = 50

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "commit_a": self.commit_a,
            "commit_b": self.commit_b,
            "files": self.files,
            "stat": self.stat,
            "rename_threshold": self.rename_threshold,
        }


class GitTracer:
    """Trace file history through git using subprocess calls."""

    def __init__(self, repo: str = ".", *, rename_threshold: int = 50, timeout: float = 30.0, ignore_whitespace: bool = False, mailmap: bool = False) -> None:
        if not 1 <= rename_threshold <= 100:
            raise GitError("rename threshold must be between 1 and 100")
        if not math.isfinite(timeout) or timeout <= 0:
            raise GitError("timeout must be a positive finite number")
        self.mailmap = mailmap
        self.ignore_whitespace = ignore_whitespace
        self.timeout = timeout
        self.rename_threshold = rename_threshold
        self.repo = os.path.realpath(os.path.expanduser(repo))
        self.path_base = self.repo

    def git(self, args: list[str], *, check: bool = True, text: bool = True) -> str:
        if self.ignore_whitespace and args and args[0] in ("log", "diff"):
            args = [args[0], "--ignore-all-space", *args[1:]]
        if self.mailmap and args and args[0] == "log":
            args = [arg.replace("%an", "%aN").replace("%ae", "%aE") if arg.startswith("--format=") else arg for arg in args]
        cmd = ["git", "--literal-pathspecs", "-C", self.repo, *args]
        try:
            result = subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitExecutionError(f"git timed out after {self.timeout:g} seconds") from exc
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
        since: str | None = None,
        until: str | None = None,
        author: str | None = None,
        follow: bool = True,
        first_parent: bool = False,
    ) -> Bloodline:
        if max_commits is not None and max_commits <= 0:
            raise GitError("max_commits must be greater than zero or None")
        self.ensure_repository()
        if not self.has_commits():
            raise GitRepositoryError("repository has no commits yet")

        path = self.normalize_path(path)

        selection: dict[str, Any] = {}
        if since:
            selection["since"] = iso_date(since)
        if until:
            selection["until"] = iso_date(until)
        if since and until and selection["since"] > selection["until"]:
            raise GitError("--since must not be later than --until")
        args = [
            "log",
            "--date=iso-strict",
            "--format=%x00%H%x00%P%x00%an%x00%ae%x00%aI%x00%s",
            "-z",
            "--no-ext-diff",
            "--no-textconv",
            "--numstat",
            f"--find-renames={self.rename_threshold}%",
        ]
        if self.ignore_whitespace:
            selection["ignore_whitespace"] = True
        if first_parent:
            args.append("--first-parent")
            selection["first_parent"] = True
        if follow:
            args.append("--follow")
        else:
            selection["follow"] = False
        if author:
            selection["author"] = author
            args.extend(["--fixed-strings", f"--author={author}"])
        if since:
            args.append(f"--since-as-filter={selection['since']}")
        if until:
            args.append(f"--until={selection['until']}")
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
                f"no matching history for {path!r}; check the path, ref, and filters"
            )

        commits = list(reversed(newest_first))
        shallow = self.git(["rev-parse", "--is-shallow-repository"]).strip() == "true"
        self._assign_roles(commits, complete=not (shallow or truncated or selection))
        return Bloodline(
            path=path,
            commits=commits,
            repo=self.root(),
            requested_ref=ref,
            followed_renames=follow,
            max_commits=max_commits,
            truncated=truncated,
            shallow=shallow,
            selection=selection,
            rename_threshold=self.rename_threshold,
            mailmap=self.mailmap,
        )

    def diff_lineage(self, commit_a: str, commit_b: str) -> DiffLineage:
        self.ensure_repository()
        if not self.has_commits():
            raise GitRepositoryError("repository has no commits yet")
        base, target = self.resolve_ref(commit_a), self.resolve_ref(commit_b)
        stat = self.git(["diff", "--no-ext-diff", "--no-textconv", "--stat", f"--find-renames={self.rename_threshold}%", base, target, "--"])
        numstat = self.git(["diff", "--no-ext-diff", "--no-textconv", "--numstat", "-z", f"--find-renames={self.rename_threshold}%", base, target, "--"])
        name_status = self.git(["diff", "--no-ext-diff", "--no-textconv", "--name-status", "-z", f"--find-renames={self.rename_threshold}%", base, target, "--"])
        files = self._merge_diff_outputs(numstat, name_status)
        return DiffLineage(
            repo=self.root(),
            commit_a=commit_a,
            commit_b=commit_b,
            files=files,
            stat=stat.rstrip(),
            rename_threshold=self.rename_threshold,
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

    def _assign_roles(self, commits: list[CommitNode], *, complete: bool = True) -> None:
        if not commits:
            return
        origin_author = commits[0].author
        heir_seen = False
        for index, commit in enumerate(commits):
            if index == 0:
                commit.role = "origin" if complete else "boundary"
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
            if self.ignore_whitespace and path not in stats_by_path:
                continue
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
