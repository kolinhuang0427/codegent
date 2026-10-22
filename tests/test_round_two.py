from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from codegent.tracer import GitTracer, GitError
from .support import RepositoryCase, ROOT


class RoundTwoTests(RepositoryCase):
    pass

    def test_explicit_repository_is_not_overridden_by_inherited_git_environment(self):
        self.write("file.py")
        self.commit()
        result = self.cli("trace", "file.py", "--json", env={
            "GIT_DIR": str(self.repo / "missing.git"), "GIT_WORK_TREE": "/missing",
            "GIT_INDEX_FILE": "/missing/index", "GIT_COMMON_DIR": "/missing/common",
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["total_commits"], 1)

    def test_historical_paths_survive_a_parent_directory_becoming_a_symlink(self):
        import tempfile
        self.write("src/file.py")
        original = self.commit()
        self.git("rm", "-r", "src")
        external = tempfile.TemporaryDirectory()
        self.addCleanup(external.cleanup)
        (self.repo / "src").symlink_to(external.name, target_is_directory=True)
        result = self.payload("trace", "src/file.py", "--ref", original)
        self.assertEqual(result["path"], "src/file.py")
        self.assertEqual(result["total_commits"], 1)

    def test_out_of_range_timezone_conversion_is_a_structured_error(self):
        self.write("file.py")
        self.commit()
        for date in ("0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00"):
            result = self.cli("trace", "file.py", "--since", date, "--json")
            self.assertEqual(result.returncode, 1)
            self.assertIn("invalid ISO date", json.loads(result.stderr)["error"])
            self.assertNotIn("Traceback", result.stderr)

    def test_file_history_rejects_directory_aggregation(self):
        self.write("src/one.py")
        self.write("src/two.py")
        self.commit()
        result = self.cli("trace", "src", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("directory", json.loads(result.stderr)["error"])
        self.assertEqual(self.payload("hotspots", "src")["matching_files"], 2)

    def test_git_notes_do_not_corrupt_structured_history(self):
        self.write("file.py")
        self.commit()
        self.git("notes", "add", "-m", "maintenance note\twith metadata")
        self.git("config", "log.showNotes", "true")
        result = self.payload("trace", "file.py")
        self.assertEqual(result["total_commits"], 1)
        self.assertEqual(result["total_additions"], 3)

    def test_malformed_git_output_returns_a_json_error(self):
        import shlex
        import shutil
        self.write("file.py")
        self.commit()
        wrapper = self.repo / "wrapper"
        wrapper.mkdir()
        fake = wrapper / "git"
        real_git = shlex.quote(shutil.which("git"))
        fake.write_text("#!/bin/sh\ncase \" $* \" in\n*\" log \"*) printf '\\000bad\\000';;\n*) exec " + real_git + " \"$@\";;\nesac\n")
        fake.chmod(0o755)
        result = self.cli("trace", "file.py", "--json", env={"PATH": str(wrapper) + os.pathsep + os.environ["PATH"]})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("cannot parse Git history", json.loads(result.stderr)["error"])
        self.assertNotIn("Traceback", result.stderr)

    def test_history_reports_pin_the_resolved_tip_even_when_a_tag_moves(self):
        self.write("file.py")
        first = self.commit()
        self.git("tag", "release")
        report = self.payload("trace", "file.py", "--ref", "release")
        self.write("file.py", "changed\n")
        second = self.commit()
        self.git("tag", "-f", "release", second)
        self.assertEqual(report["resolved_ref"], first)
        self.assertEqual(self.payload("authors", "file.py", "--ref", "release")["resolved_ref"], second)

    def test_diff_summary_preserves_resolved_refs_and_comparison_settings(self):
        self.write("file.py")
        base = self.commit()
        self.write("file.py", "changed\n")
        target = self.commit()
        report = self.payload("diff", "HEAD~1", "HEAD", "--summary", "--ignore-whitespace")
        self.assertEqual((report["resolved_a"], report["resolved_b"]), (base, target))
        self.assertTrue(report["ignore_whitespace"])
        self.assertNotIn("files", report)

    def test_partial_or_binary_history_does_not_invent_net_line_totals(self):
        self.write("file.py")
        self.commit()
        self.write("file.py", "one\ntwo\nthree\nfour\n")
        self.commit()
        self.assertEqual(self.payload("trace", "file.py")["current_carried_lines"], 4)
        partial = self.payload("trace", "file.py", "--max-commits", "1")
        self.assertIsNone(partial["current_carried_lines"])
        self.assertIsNone(partial["genes"][0]["carried_lines"])
        self.assertIsNone(partial["age_days"])
        (self.repo / "binary.dat").write_bytes(b"\0data")
        self.commit()
        self.assertIsNone(self.payload("trace", "binary.dat")["current_carried_lines"])

    def test_python_api_rejects_boolean_fractional_and_invalid_limits(self):
        self.write("file.py")
        self.commit()
        tracer = GitTracer(str(self.repo))
        for limit in (True, 1.5, "10", -1):
            with self.subTest(limit=limit), self.assertRaises(GitError):
                tracer.trace_path("file.py", max_commits=limit)
        for threshold in (True, 25.5, "50"):
            with self.assertRaises(GitError):
                GitTracer(str(self.repo), rename_threshold=threshold)
        with self.assertRaises(GitError):
            GitTracer(str(self.repo), timeout=True)

    def test_commit_message_search_is_literal_and_marks_filtered_history(self):
        self.write("file.py")
        self.commit("add [parser]")
        self.write("file.py", "updated\n")
        self.commit("unrelated")
        report = self.payload("trace", "file.py", "--grep", "[parser]")
        self.assertEqual(report["total_commits"], 1)
        self.assertEqual(report["selection"]["grep"], "[parser]")
        self.assertFalse(report["origin_confirmed"])
        self.assertEqual(self.payload("hotspots", "--grep", "[parser]")["scanned_commits"], 1)

    def test_hotspots_can_exclude_generated_or_vendor_path_globs(self):
        self.write("src/file.py")
        self.write("vendor/generated.py")
        self.write("build/output.py")
        self.commit()
        report = self.payload("hotspots", "--exclude", "vendor/*", "--exclude", "build/*")
        self.assertEqual([row["path"] for row in report["files"]], ["src/file.py"])
        self.assertEqual(report["excludes"], ["vendor/*", "build/*"])
