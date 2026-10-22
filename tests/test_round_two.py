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

    def test_current_only_hotspots_follow_the_selected_tip(self):
        self.write("gone.py")
        self.write("present.py")
        original = self.commit()
        self.git("rm", "gone.py")
        self.commit()
        current = self.payload("hotspots", "--current-only")
        self.assertEqual([row["path"] for row in current["files"]], ["present.py"])
        self.assertTrue(current["current_only"])
        self.assertEqual(self.payload("hotspots", "--current-only", "--ref", original)["matching_files"], 2)

    def test_authors_can_group_name_variants_by_email(self):
        self.write("file.py")
        self.commit()
        self.write("file.py", "changed\n")
        self.commit(env={"GIT_AUTHOR_NAME": "Another Name", "GIT_AUTHOR_EMAIL": "first@example.test"})
        self.assertEqual(self.payload("authors", "file.py")["total_authors"], 2)
        report = self.payload("authors", "file.py", "--group-by", "email")
        self.assertEqual(report["total_authors"], 1)
        self.assertEqual(report["authors"][0]["commits"], 2)
        self.assertEqual(len(report["authors"][0]["identities"]), 2)

    def test_author_thresholds_disclose_omitted_contributors(self):
        self.write("file.py")
        self.commit()
        self.write("file.py", "second\n")
        self.commit()
        self.write("file.py", "third\n")
        self.commit(env={"GIT_AUTHOR_NAME": "Second", "GIT_AUTHOR_EMAIL": "second@example.test"})
        report = self.payload("authors", "file.py", "--min-commits", "2")
        self.assertEqual(report["total_authors"], 2)
        self.assertEqual(report["matching_authors"], 1)
        self.assertEqual(report["omitted_authors"], 1)
        self.assertEqual(report["authors"][0]["commits"], 2)

    def test_timeline_groups_author_dates_in_utc(self):
        self.write("file.py")
        self.commit(env={"GIT_AUTHOR_DATE": "2026-01-31T23:30:00-02:00", "GIT_COMMITTER_DATE": "2026-02-01T01:30:00Z"})
        self.write("file.py", "two\n")
        self.commit(env={"GIT_AUTHOR_DATE": "2026-02-15T12:00:00Z", "GIT_COMMITTER_DATE": "2026-02-15T12:00:00Z"})
        self.write("other.py")
        self.commit(env={"GIT_AUTHOR_DATE": "2026-03-01T12:00:00Z", "GIT_COMMITTER_DATE": "2026-03-01T12:00:00Z"})
        report = self.payload("timeline")
        self.assertEqual([row["period"] for row in report["periods"]], ["2026-02", "2026-03"])
        self.assertEqual([row["commits"] for row in report["periods"]], [2, 1])
        self.assertIn("# codegent timeline", self.cli("timeline", "--markdown").stdout)

    def test_cochange_ranks_companions_without_claiming_dependencies(self):
        for name in ("a.py", "b.py", "c.py"):
            self.write(name)
        self.commit()
        self.write("a.py", "changed\n")
        self.write("b.py", "changed\n")
        self.commit()
        result = self.payload("cochange", "a.py")
        self.assertEqual(result["target_commits"], 2)
        self.assertEqual([(r["path"], r["shared_commits"]) for r in result["files"]], [("b.py", 2), ("c.py", 1)])
        filtered = self.payload("cochange", "a.py", "--min-shared", "2")
        self.assertEqual(filtered["matching_files"], 1)
        self.assertIn("not a dependency", filtered["interpretation"])

    def test_files_lists_historical_objects_and_executable_modes(self):
        name = "src/中文\tfile.py"
        self.write(name, "abc\n")
        self.write("tool.sh", "#!/bin/sh\n")
        (self.repo / "tool.sh").chmod(0o755)
        original = self.commit()
        self.write("new.py")
        self.commit()
        report = self.payload("files", "--ref", original)
        self.assertEqual(report["total_files"], 2)
        rows = {row["path"]: row for row in report["files"]}
        self.assertEqual(rows[name]["size"], 4)
        self.assertEqual(rows["tool.sh"]["mode"], "100755")
        self.assertTrue(self.payload("files", "--limit", "1")["truncated"])

    def test_source_previews_committed_text_with_line_and_byte_bounds(self):
        self.write("file.py", "one\ntwo\nthree")
        original = self.commit()
        self.write("file.py", "uncommitted\n")
        report = self.payload("source", "file.py", "--ref", original, "--lines", "2:2")
        self.assertEqual(report["content"], "two\n")
        self.assertEqual(report["lines"], [{"number": 2, "text": "two"}])
        self.assertEqual(self.payload("source", "file.py")["file_lines"], 3)
        oversized = self.cli("source", "file.py", "--max-bytes", "3", "--json")
        self.assertIn("exceeds", json.loads(oversized.stderr)["error"])
        self.assertIn("# codegent source", self.cli("source", "file.py", "--markdown").stdout)

    def test_merge_base_comparison_omits_unrelated_base_branch_changes(self):
        self.write("shared.py")
        common = self.commit()
        self.git("checkout", "-b", "feature")
        self.write("feature.py")
        self.commit()
        self.git("checkout", "main")
        self.write("main.py")
        main_tip = self.commit()
        report = self.payload("diff", "main", "feature", "--merge-base")
        self.assertEqual([row["path"] for row in report["files"]], ["feature.py"])
        self.assertEqual(report["resolved_a"], common)
        self.assertEqual(report["input_a_resolved"], main_tip)
        self.assertTrue(report["merge_base"])

    def test_diff_distinguishes_copies_from_renames(self):
        self.write("original.py")
        base = self.commit()
        self.write("copy.py")
        self.commit()
        self.assertEqual(self.payload("diff", base, "HEAD")["files"][0]["status"], "added")
        report = self.payload("diff", base, "HEAD", "--find-copies")
        item, = report["files"]
        self.assertEqual(item["status"], "copied")
        self.assertEqual(item["copied_from"], "original.py")
        self.assertEqual(item["copied_to"], "copy.py")
        self.assertNotIn("renamed_from", item)
        self.assertEqual(report["summary"]["statuses"], {"copied": 1})
