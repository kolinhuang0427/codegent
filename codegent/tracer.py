"""Git-backed history traversal for codegent."""

from __future__ import annotations

import os
import math
import re
import subprocess
from dataclasses import dataclass, field
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


def positive_count(value: int | None, name: str, *, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    if type(value) is not int or value <= 0:
        raise GitError(f"{name} must be a positive integer" + (" or None" if allow_none else ""))


def iso_date(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError) as exc:
        raise GitError(f"invalid ISO date: {value!r}") from exc


@dataclass(slots=True)
class DiffLineage:
    repo: str
    commit_a: str
    commit_b: str
    files: list[dict[str, Any]]
    stat: str
    paths: list[str] = field(default_factory=list)
    rename_threshold: int = 50
    merge_base: bool = False
    input_a_resolved: str = ""
    resolved_a: str = ""
    resolved_b: str = ""
    ignore_whitespace: bool = False

    @property
    def summary(self) -> dict[str, Any]:
        statuses: dict[str, int] = {}
        for item in self.files:
            status = item["status"]
            statuses[status] = statuses.get(status, 0) + 1
        return {"files": len(self.files), "additions": sum(item["additions"] for item in self.files),
                "deletions": sum(item["deletions"] for item in self.files),
                "binary_files": sum(int(item["binary"]) for item in self.files), "statuses": statuses}

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "commit_a": self.commit_a,
            "commit_b": self.commit_b,
            "resolved_a": self.resolved_a,
            "merge_base": self.merge_base,
            "input_a_resolved": self.input_a_resolved,
            "resolved_b": self.resolved_b,
            "ignore_whitespace": self.ignore_whitespace,
            "files": self.files,
            "stat": self.stat,
            "summary": self.summary,
            "paths": self.paths,
            "rename_threshold": self.rename_threshold,
        }


class GitTracer:
    """Trace file history through git using subprocess calls."""

    def __init__(self, repo: str = ".", *, rename_threshold: int = 50, timeout: float = 30.0, ignore_whitespace: bool = False, mailmap: bool = False) -> None:
        if type(rename_threshold) is not int or not 1 <= rename_threshold <= 100:
            raise GitError("rename threshold must be between 1 and 100")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
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
        cmd = ["git", "-c", "color.ui=false", "-c", "log.showSignature=false",
               "-c", "i18n.logOutputEncoding=UTF-8", "--literal-pathspecs", "-C", self.repo, *args]
        environment = dict(os.environ)
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX"):
            environment.pop(key, None)
        try:
            result = subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                timeout=self.timeout,
                env=environment,
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
        if os.path.commonpath([self.repo, absolute]) != self.repo:
            # Resolve aliases of the repository root, not tracked symlink parents.
            ancestor = absolute
            while os.path.realpath(ancestor) != self.repo:
                parent = os.path.dirname(ancestor)
                if parent == ancestor:
                    raise GitError(f"path is outside the repository: {path!r}")
                ancestor = parent
            absolute = os.path.join(self.repo, os.path.relpath(absolute, ancestor))
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

    def trace_path(self, path: str, ref: str = "HEAD", **options: Any) -> Bloodline:
        return self._read_history(path, ref, **options)

    def repository_history(self, path: str = ".", ref: str = "HEAD", **options: Any) -> Bloodline:
        options.pop("follow", None)
        return self._read_history(path, ref, follow=None, allow_empty=True, **options)

    def _read_history(
        self,
        path: str,
        ref: str = "HEAD",
        *,
        max_commits: int | None = 10000,
        since: str | None = None,
        until: str | None = None,
        author: str | None = None,
        grep: str | None = None,
        follow: bool | None = True,
        allow_empty: bool = False,
        first_parent: bool = False,
    ) -> Bloodline:
        positive_count(max_commits, "max_commits", allow_none=True)
        self.ensure_repository()
        if not self.has_commits():
            raise GitRepositoryError("repository has no commits yet")

        path = self.normalize_path(path)
        resolved = self.resolve_ref(ref)
        if follow is not None and self.git(["cat-file", "-t", f"{resolved}:{path}"], check=False).strip() == "tree":
            raise GitError("path is a directory; use hotspots for directory activity")

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
            "--no-notes",
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
        elif follow is False:
            selection["follow"] = False
        if grep:
            selection["grep"] = grep
            args.extend(["--fixed-strings", f"--grep={grep}"])
        if author:
            selection["author"] = author
            args.extend(["--fixed-strings", f"--author={author}"])
        if since:
            args.append(f"--since-as-filter={selection['since']}")
        if until:
            args.append(f"--until={selection['until']}")
        if max_commits is not None and max_commits > 0:
            args.append(f"--max-count={max_commits + 1}")
        args.extend([resolved, "--", path])

        output = self.git(args)
        newest_first = self._parse_log(output)
        truncated = max_commits is not None and len(newest_first) > max_commits
        if truncated:
            newest_first = newest_first[:max_commits]
        if not newest_first and not allow_empty:
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
            resolved_ref=resolved,
            followed_renames=bool(follow),
            max_commits=max_commits,
            truncated=truncated,
            shallow=shallow,
            selection=selection,
            rename_threshold=self.rename_threshold,
            mailmap=self.mailmap,
        )

    def tracked_files(self, path: str = ".", ref: str = "HEAD", *, limit: int = 1000) -> dict[str, Any]:
        positive_count(limit, "limit")
        path = self.normalize_path(path)
        resolved = self.resolve_ref(ref)
        output = self.git(["ls-tree", "-r", "-l", "-z", "--full-tree", resolved, "--", path])
        files = []
        for record in output.split("\0"):
            if not record:
                continue
            metadata, filename = record.split("\t", 1)
            mode, kind, oid, size = metadata.split()
            files.append({"path": filename, "mode": mode, "type": kind, "object_id": oid,
                          "size": None if size == "-" else int(size)})
        return {"repo": self.repo, "path": path, "requested_ref": ref, "resolved_ref": resolved,
                "total_files": len(files), "total_bytes": sum(item["size"] or 0 for item in files),
                "truncated": len(files) > limit, "files": files[:limit]}

    def source(self, path: str, ref: str = "HEAD", *, lines: str | None = None, max_bytes: int = 1048576) -> dict[str, Any]:
        positive_count(max_bytes, "max_bytes")
        path = self.normalize_path(path)
        resolved = self.resolve_ref(ref)
        object_name = f"{resolved}:{path}"
        if self.git(["cat-file", "-t", object_name]).strip() != "blob":
            raise GitError("source preview requires a file blob")
        size = int(self.git(["cat-file", "-s", object_name]).strip())
        if size > max_bytes:
            raise GitError(f"source blob exceeds --max-bytes={max_bytes}")
        content = self.git(["cat-file", "blob", object_name])
        if "\0" in content:
            raise GitError("source preview is unavailable for binary files")
        parts = content.split("\n")
        file_lines = [part + "\n" for part in parts[:-1]]
        if parts[-1]:
            file_lines.append(parts[-1])
        start, end = 1, len(file_lines)
        if lines:
            match = re.fullmatch(r"([1-9][0-9]*):([1-9][0-9]*)", lines)
            if not match:
                raise GitError("--lines must be START:END with positive line numbers")
            start, end = map(int, match.groups())
            if start > end or end > len(file_lines):
                raise GitError("line range is outside the file")
        selected = file_lines[start - 1:end]
        return {"repo": self.repo, "path": path, "requested_ref": ref, "resolved_ref": resolved,
                "size": size, "file_lines": len(file_lines), "line_range": lines,
                "content": "".join(selected),
                "lines": [{"number": start + i, "text": line.removesuffix("\n")} for i, line in enumerate(selected)]}

    def owners(self, path: str, ref: str = "HEAD", *, lines: str | None = None) -> dict[str, Any]:
        path = self.normalize_path(path)
        commit = self.resolve_ref(ref)
        source = self.git(["cat-file", "blob", f"{commit}:{path}"])
        if "\0" in source:
            raise GitError("line ownership is unavailable for binary files")
        file_lines = source.count("\n") + int(bool(source) and not source.endswith("\n"))
        args = ["blame", "--line-porcelain"]
        if self.ignore_whitespace:
            args.append("-w")
        if lines:
            match = re.fullmatch(r"([1-9][0-9]*):([1-9][0-9]*)", lines)
            if not match:
                raise GitError("--lines must be START:END with positive line numbers")
            start, end = map(int, match.groups())
            if start > end or end > file_lines:
                raise GitError("line range is outside the file")
            args.extend(["-L", f"{start},{end}"])
        args.extend([commit, "--", path])
        owners: dict[str, dict[str, Any]] = {}
        current: dict[str, str] = {}
        for line in self.git(args).split("\n"):
            if re.match(r"^[0-9a-f]{40,64} ", line):
                current = {"commit": line.split(" ", 1)[0]}
            elif line == "boundary":
                current["boundary"] = "true"
            elif line.startswith("author "):
                current["name"] = line[7:]
            elif line.startswith("author-mail "):
                current["email"] = line[12:].strip("<>")
            elif line.startswith("\t"):
                identity = f"{current['name']} <{current['email']}>"
                row = owners.setdefault(identity, {"author": identity, "lines": 0, "boundary_lines": 0, "commits": set()})
                row["lines"] += 1
                row["boundary_lines"] += int(current.get("boundary") == "true")
                row["commits"].add(current["commit"])
        total = sum(row["lines"] for row in owners.values())
        rows = sorted(owners.values(), key=lambda row: (-row["lines"], row["author"]))
        for row in rows:
            row["commits"] = sorted(row["commits"])
            row["percentage"] = round(row["lines"] * 100 / total, 2) if total else 0
        shallow = self.git(["rev-parse", "--is-shallow-repository"]).strip() == "true"
        warnings = ["Shallow repository: blame may attribute older lines to a boundary commit."] if shallow else []
        return {"repo": self.repo, "path": path, "requested_ref": ref, "resolved_ref": commit,
                "shallow": shallow, "history_complete": not shallow, "warnings": warnings,
                "file_lines": file_lines, "selected_lines": total, "line_range": lines,
                "owners": rows, "attribution": "Git blame at the selected commit; not code quality or legal ownership"}

    def diff_lineage(self, commit_a: str, commit_b: str, *, paths: list[str] | None = None, merge_base: bool = False) -> DiffLineage:
        self.ensure_repository()
        if not self.has_commits():
            raise GitRepositoryError("repository has no commits yet")
        selected_paths = [self.normalize_path(path) for path in (paths or [])]
        base, target = self.resolve_ref(commit_a), self.resolve_ref(commit_b)
        input_a_resolved = base
        if merge_base:
            bases = self.git(["merge-base", "--all", base, target], check=False).splitlines()
            if len(bases) != 1:
                raise GitError("comparison requires exactly one merge base; choose explicit refs")
            base = bases[0]
        stat = self.git(["diff", "--no-ext-diff", "--no-textconv", "--stat", f"--find-renames={self.rename_threshold}%", base, target, "--", *selected_paths])
        numstat = self.git(["diff", "--no-ext-diff", "--no-textconv", "--numstat", "-z", f"--find-renames={self.rename_threshold}%", base, target, "--", *selected_paths])
        name_status = self.git(["diff", "--no-ext-diff", "--no-textconv", "--name-status", "-z", f"--find-renames={self.rename_threshold}%", base, target, "--", *selected_paths])
        files = self._merge_diff_outputs(numstat, name_status)
        return DiffLineage(
            repo=self.root(),
            commit_a=commit_a,
            commit_b=commit_b,
            resolved_a=base,
            merge_base=merge_base,
            input_a_resolved=input_a_resolved,
            resolved_b=target,
            ignore_whitespace=self.ignore_whitespace,
            files=files,
            stat=stat.rstrip(),
            paths=selected_paths,
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
        try:
            return self._decode_log(output)
        except (IndexError, ValueError, KeyError) as exc:
            raise GitError("cannot parse Git history output") from exc

    def _decode_log(self, output: str) -> list[CommitNode]:
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
                node.changes.append(item)
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
        try:
            return self._decode_diff(numstat, name_status)
        except (IndexError, ValueError, KeyError) as exc:
            raise GitError("cannot parse Git comparison output") from exc

    def _decode_diff(self, numstat: str, name_status: str) -> list[dict[str, Any]]:
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
