from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codegent.cli import _write_output
from codegent.models import Bloodline, CommitNode
from codegent.tracer import GitTracer
from .support import RepositoryCase


class ReviewFixTests(RepositoryCase):
    def test_empty_paths_cannot_broaden_comparisons(self):
        self.write("a")
        base = self.commit()
        self.write("a", "changed\n")
        self.commit()
        for command in ("diff", "patch"):
            result = self.cli(command, base, "HEAD", "--path", "", "--json")
            self.assertEqual(result.returncode, 1)
            self.assertIn("nonempty", json.loads(result.stderr)["error"])

    def test_external_subdirectory_alias_preserves_literal_git_path(self):
        self.write("src/file.py")
        self.commit()
        with tempfile.TemporaryDirectory() as folder:
            alias = Path(folder) / "alias"
            os.symlink(self.repo / "src", alias)
            report = self.payload("trace", str(alias / "file.py"))
            self.assertEqual(report["path"], "src/file.py")

    def test_windows_git_root_normalization(self):
        import ntpath
        tracer = GitTracer(str(self.repo))
        tracer.repo, tracer.path_base = "C:/Repo", "c:\\repo"
        with patch("codegent.tracer.os.path", ntpath), patch.object(ntpath, "isdir", return_value=True), patch.object(tracer, "git", side_effect=lambda args: "true\n" if args[-1] == "--is-inside-work-tree" else "C:/Repo\n"):
            self.assertEqual(tracer.normalize_path("file.py"), "file.py")

    def test_legacy_model_positional_arguments_keep_their_meaning(self):
        history = Bloodline("a", [], "repo", "HEAD", False, 10, True)
        self.assertFalse(history.followed_renames)
        self.assertEqual(history.max_commits, 10)
        self.assertTrue(history.truncated)
        commit = CommitNode("abc", [], "Name", "mail", "2024-01-01", "subject", 7, 2)
        self.assertEqual((commit.additions, commit.deletions), (7, 2))

    def test_doctor_includes_untracked_files_hidden_by_git_config(self):
        self.write("a")
        self.commit()
        self.git("config", "status.showUntrackedFiles", "no")
        self.write("untracked")
        self.assertFalse(self.payload("doctor")["working_tree_clean"])

    def test_abbreviated_merge_options_are_rejected(self):
        self.assertEqual(self.cli("--merg", "timeline", "--no-merg").returncode, 2)
        self.assertEqual(self.cli("cochange", "a", "--mailmap").returncode, 2)

    def test_export_permission_fallback_without_fchmod(self):
        target = self.repo / "out.txt"
        target.write_text("old")
        os.chmod(target, 0o640)
        original = os.fchmod
        del os.fchmod
        try:
            _write_output("new", str(target))
        finally:
            os.fchmod = original
        self.assertEqual(target.read_text(), "new\n")
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)

    @unittest.skipUnless(os.name == "posix", "POSIX process group coverage")
    def test_timeout_terminates_git_helpers_in_the_same_process_group(self):
        import shlex
        import subprocess
        pidfile = self.repo / "child.pid"
        wrapper = self.repo / "git"
        wrapper.write_text("#!/bin/sh\n/bin/sleep 20 &\necho $! > " + shlex.quote(str(pidfile)) + "\nwait\n")
        wrapper.chmod(0o755)
        result = self.cli("doctor", "--timeout", "1", "--json", env={"PATH": str(self.repo)})
        self.assertEqual(result.returncode, 1)
        self.assertIn("timed out", json.loads(result.stderr)["error"])
        pid = int(pidfile.read_text())
        status = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
        self.assertTrue(status.returncode != 0 or status.stdout.strip().startswith("Z"), status.stdout)

    def test_platform_timeout_overflow_is_a_readable_git_error(self):
        from unittest.mock import Mock
        from codegent.tracer import GitExecutionError
        process = Mock()
        process.communicate.side_effect = OverflowError("timeout out of range")
        tracer = GitTracer(str(self.repo), timeout=1000000000)
        with patch("codegent.tracer.subprocess.Popen", return_value=process), patch.object(tracer, "_terminate_git") as stop:
            with self.assertRaisesRegex(GitExecutionError, "supported range"):
                tracer.git(["--version"])
            stop.assert_called_once_with(process)
