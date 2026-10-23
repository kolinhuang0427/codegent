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

    def test_ascii_preserves_repository_drawing_characters(self):
        name = "│◆•.py"
        self.write(name)
        self.commit("keep │◆• in subject")
        for command in ("trace", "ancestry", "genemap", "bloodline"):
            result = self.cli(command, name, "--ascii")
            self.assertEqual(result.returncode, 0, result.stderr)
            if command != "bloodline":
                self.assertIn(name, result.stdout)
        self.assertIn("keep │◆• in subject", self.cli("trace", name, "--ascii").stdout)

    def test_markdown_summary_and_ownership_scope_are_preserved(self):
        self.write("a")
        self.commit()
        bloodline = self.cli("bloodline", "a", "--markdown")
        self.assertIn("Genetic diversity", bloodline.stdout)
        self.assertIn("Current net line trace", bloodline.stdout)
        owners = self.cli("owners", "a", "--lines", "2:2", "--markdown")
        self.assertIn("Selected lines: 1 of 3; range: 2:2", owners.stdout)
        authors = self.payload("authors", "a", "--mailmap", "--rename-threshold", "100")
        self.assertEqual(authors["rename_threshold"], 100)
        self.assertTrue(authors["mailmap"])
        self.assertFalse(authors["history_complete"])

    def test_markdown_comparisons_preserve_binary_provenance_and_statuses(self):
        self.write("old", "original\n" * 20)
        base = self.commit()
        self.git("mv", "old", "new")
        (self.repo / "binary").write_bytes(b"\0binary")
        self.commit()
        md = self.cli("diff", base, "HEAD", "--markdown").stdout
        self.assertIn("| new | old | renamed |", md)
        self.assertIn("unavailable", md)
        self.assertIn("| binary |", md)
        summary = self.cli("diff", base, "HEAD", "--summary", "--markdown").stdout
        self.assertIn("| renamed | 1 |", summary)
        filtered = self.cli("diff", base, "HEAD", "--status", "deleted").stdout
        self.assertIn("No changes matched", filtered)
        self.assertIn("2 before filtering", filtered)

    def test_empty_csv_and_binary_timeline_columns_match_requested_report(self):
        import csv, io
        (self.repo / "binary").write_bytes(b"\0binary")
        self.commit()
        for flag in ("--no-color", "--markdown"):
            rendered = self.cli("timeline", "--cumulative", flag).stdout
            self.assertIn("Binary changes", rendered)
            self.assertIn("Total binary changes", rendered)
        empty = self.cli("timeline", "--grep", "absent", "--cumulative", "--csv")
        header = csv.DictReader(io.StringIO(empty.stdout)).fieldnames
        self.assertIn("cumulative_binary_changes", header)
        self.assertIn("cumulative_commits", header)
        empty = self.cli("hotspots", "--min-commits", "2", "--csv")
        header = csv.DictReader(io.StringIO(empty.stdout)).fieldnames
        self.assertTrue({"authors", "first_changed", "last_changed"} <= set(header))

    def test_default_file_report_includes_object_ids(self):
        self.write("a")
        self.commit()
        oid = self.git("rev-parse", "HEAD:a")
        self.assertIn(oid, self.cli("files").stdout)

    def test_historical_binary_attributes_apply_without_touching_real_index(self):
        self.write("plain.dat", "readable bytes\n")
        self.write(".gitattributes", "*.dat binary\n")
        binary_tip = self.commit()
        self.write(".gitattributes", "*.dat diff\n")
        self.commit()
        index_before = (self.repo / ".git/index").read_bytes()
        for command in ("source", "owners"):
            binary = self.cli(command, "plain.dat", "--ref", binary_tip, "--json")
            self.assertEqual(binary.returncode, 1)
            self.assertIn("binary", json.loads(binary.stderr)["error"])
            self.assertEqual(self.cli(command, "plain.dat").returncode, 0)
        self.assertEqual((self.repo / ".git/index").read_bytes(), index_before)

    def test_binary_diff_driver_configuration_is_honored(self):
        self.write("plain.dat", "readable bytes\n")
        self.write(".gitattributes", "*.dat diff=asset\n")
        self.commit()
        self.git("config", "diff.asset.binary", "true")
        self.assertEqual(self.cli("source", "plain.dat").returncode, 1)
        self.assertEqual(self.cli("owners", "plain.dat").returncode, 1)

    def test_copy_detection_keeps_sources_outside_selected_destination(self):
        content = "original content\n" * 20
        self.write("src/original", content)
        self.write("other", "old\n")
        base = self.commit()
        self.write("dst/copy", content)
        self.write("other", "new\n")
        self.commit()
        report = self.payload("diff", base, "HEAD", "--path", "dst", "--find-copies")
        self.assertEqual(report["total_changed_files"], 1)
        self.assertEqual(report["files"][0]["status"], "copied")
        self.assertEqual(report["files"][0]["copied_from"], "src/original")
        self.assertEqual(report["stat"], "")
        patch = self.payload("patch", base, "HEAD", "--path", "dst", "--find-copies")["patch"]
        self.assertIn("copy from src/original", patch)
        self.assertIn("copy to dst/copy", patch)
        self.assertNotIn("diff --git a/other", patch)
        self.assertEqual(self.payload("patch", base, "HEAD", "--path", "missing", "--find-copies")["patch"], "")

    def test_copy_patch_alignment_preserves_newline_paths(self):
        content = "original content\n" * 20
        self.write("src/old\nname", content)
        base = self.commit()
        self.write("dst/new\nname", content)
        self.commit()
        report = self.payload("diff", base, "HEAD", "--path", "dst", "--find-copies")
        self.assertEqual(report["files"][0]["copied_from"], "src/old\nname")
        patch = self.payload("patch", base, "HEAD", "--path", "dst", "--find-copies")["patch"]
        self.assertIn("copy from", patch)
        self.assertIn("old\\nname", patch)
