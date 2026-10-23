from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from codegent.tracer import GitTracer, GitError
from .support import RepositoryCase, ROOT


class RoundFourTests(RepositoryCase):
    pass

    def test_blame_ignores_implicit_repository_ignore_file(self):
        self.write("a")
        self.commit()
        self.write("a", "one\ntwo changed\nthree\n")
        latest = self.commit()
        self.write("ignored.txt", latest + "\n")
        self.git("config", "blame.ignoreRevsFile", str(self.repo / "ignored.txt"))
        report = self.payload("owners", "a")
        self.assertEqual(report["selected_lines"], 3)
        self.assertIn(latest, report["owners"][0]["commits"])
        self.assertIsNone(report["ignore_revs_file"])
        explicit = self.cli("owners", "a", "--ignore-revs-file", "missing-ignore-file")
        self.assertNotEqual(explicit.returncode, 0)

    def test_patch_prefixes_do_not_depend_on_repository_config(self):
        self.write("a")
        base = self.commit()
        self.write("a", "changed\n")
        self.commit()
        self.git("config", "diff.noprefix", "true")
        self.git("config", "diff.mnemonicPrefix", "true")
        patch = self.payload("patch", base, "HEAD")["patch"]
        self.assertIn("diff --git a/a b/a", patch)
        self.assertIn("--- a/a", patch)
        self.assertIn("+++ b/a", patch)

    def test_repository_ranges_include_empty_commits_and_merges(self):
        self.write("a")
        base = self.commit()
        self.git("commit", "--allow-empty", "-m", "empty checkpoint")
        empty = self.git("rev-parse", "HEAD")
        self.git("checkout", "-b", "side", base)
        self.write("b")
        self.commit("side change")
        self.git("checkout", "main")
        self.git("merge", "--no-ff", "side", "-m", "integration")
        merged = self.git("rev-parse", "HEAD")
        report = self.payload("commits", base, "HEAD")
        hashes = {r["hash"] for r in report["commits"]}
        self.assertIn(empty, hashes)
        self.assertIn(merged, hashes)
        self.assertEqual(report["total_commits"], 3)
        scoped = self.payload("commits", base, "HEAD", "--path", "b")
        self.assertEqual(scoped["total_commits"], 1)

    def test_history_filters_can_ignore_case(self):
        self.write("a")
        self.commit("Fix MixedCASE")
        self.assertEqual(self.payload("timeline", "--grep", "mixedcase")["periods"], [])
        report = self.payload("timeline", "--grep", "mixedcase", "--ignore-case")
        self.assertEqual(sum(r["commits"] for r in report["periods"]), 1)
        self.assertTrue(report["selection"]["ignore_case"])
        self.assertEqual(self.payload("authors", "a", "--author", "FIRST AUTHOR", "--ignore-case")["total_authors"], 1)
        self.assertEqual(self.cli("files", "--ignore-case", "--grep", "a").returncode, 2)
        self.assertEqual(self.cli("trace", "a", "--ignore-case").returncode, 2)

    def test_history_merge_selection(self):
        self.write("a")
        base = self.commit()
        self.git("checkout", "-b", "side")
        self.write("b")
        self.commit()
        self.git("checkout", "main")
        self.git("merge", "--no-ff", "side", "-m", "integration")
        merges = self.payload("commits", base, "HEAD", "--merges")
        self.assertEqual(merges["total_commits"], 1)
        self.assertEqual(len(merges["commits"][0]["parents"]), 2)
        self.assertEqual(self.payload("commits", base, "HEAD", "--no-merges")["total_commits"], 1)
        self.assertEqual(self.cli("files", "--merges").returncode, 2)
        self.assertEqual(self.cli("--merges", "timeline", "--no-merges").returncode, 2)

    def test_range_ancestry_path_excludes_unrelated_side_history(self):
        self.write("root")
        root = self.commit()
        self.write("main")
        base = self.commit()
        self.git("checkout", "-b", "side", root)
        self.write("side")
        side = self.commit()
        self.git("checkout", "main")
        self.git("merge", "--no-ff", "side", "-m", "join")
        all_rows = self.payload("commits", base, "HEAD")
        filtered = self.payload("commits", base, "HEAD", "--ancestry-path")
        self.assertIn(side, {r["hash"] for r in all_rows["commits"]})
        self.assertNotIn(side, {r["hash"] for r in filtered["commits"]})
        self.assertEqual(filtered["total_commits"], 1)
        self.assertTrue(filtered["selection"]["ancestry_path"])

    def test_refs_can_find_releases_and_branches_containing_a_commit(self):
        self.write("a")
        old = self.commit()
        self.git("branch", "old", old)
        self.write("a", "new\n")
        new = self.commit()
        self.git("tag", "-a", "release", "-m", "release")
        report = self.payload("refs", "--contains", new)
        self.assertEqual({r["short_name"] for r in report["refs"]}, {"main", "release"})
        self.assertEqual(report["contains_resolved"], new)
        self.assertEqual(self.cli("refs", "--contains", "missing").returncode, 1)

    def test_refs_can_identify_exact_commit_labels(self):
        self.write("a")
        old = self.commit()
        self.git("tag", "older")
        self.write("a", "updated\n")
        tip = self.commit()
        self.git("tag", "-a", "annotated", "-m", "release")
        self.git("tag", "lightweight")
        report = self.payload("refs", "--points-at", "HEAD", "--contains", old)
        self.assertEqual({r["short_name"] for r in report["refs"]}, {"main", "annotated", "lightweight"})
        self.assertEqual(report["points_at_resolved"], tip)
        self.assertEqual(self.payload("refs", "--points-at", old)["total_refs"], 1)

    def test_ref_version_and_creator_date_sorting(self):
        self.write("a")
        old = self.commit(env={"GIT_COMMITTER_DATE": "2024-01-01T00:00:00Z"})
        self.git("tag", "v2", old)
        self.git("tag", "v10", old)
        self.write("a", "changed\n")
        self.commit(env={"GIT_COMMITTER_DATE": "2024-02-01T00:00:00Z"})
        self.git("tag", "v3")
        report = self.payload("refs", "--kind", "tag", "--sort", "version")
        self.assertEqual([r["short_name"] for r in report["refs"]], ["v2", "v3", "v10"])
        newest = self.payload("refs", "--kind", "tag", "--sort", "date", "--limit", "1")
        self.assertEqual(newest["refs"][0]["short_name"], "v3")
        self.assertTrue(newest["truncated"])

    def test_ref_patterns_filter_before_limits_and_export_peeled_type(self):
        self.write("a")
        self.commit()
        for tag in ("release/v1", "release/v2", "other"):
            self.git("tag", "-a", tag, "-m", tag)
        report = self.payload("refs", "--kind", "tag", "--match", "release/*", "--limit", "1")
        self.assertEqual(report["total_refs"], 2)
        self.assertEqual(report["scanned_refs"], 3)
        self.assertTrue(report["truncated"])
        both = self.payload("refs", "--kind", "tag", "--match", "release/v1", "--match", "other")
        self.assertEqual(both["total_refs"], 2)
        result = self.cli("refs", "--kind", "tag", "--csv")
        row = list(csv.DictReader(io.StringIO(result.stdout)))[0]
        self.assertEqual(row["peeled_type"], "commit")
        self.assertNotIn("peeled_object_type", row)

    def test_file_byte_bounds_are_inclusive_and_precede_limit(self):
        self.write("empty", "")
        self.write("small", "abc")
        self.write("large", "abcdefghij")
        self.commit()
        report = self.payload("files", "--min-bytes", "3", "--max-bytes", "3", "--limit", "1")
        self.assertEqual([r["path"] for r in report["files"]], ["small"])
        self.assertEqual(report["total_files"], 3)
        self.assertEqual(report["matching_files"], 1)
        self.assertEqual(report["total_bytes"], 3)
        self.assertEqual(self.payload("files", "--max-bytes", "0")["files"][0]["path"], "empty")
        self.assertEqual(self.cli("files", "--min-bytes", "4", "--max-bytes", "3").returncode, 1)
        self.assertEqual(len(GitTracer(str(self.repo)).tracked_files(limit=None)["files"]), 3)

    def test_file_globs_filter_paths_before_ranking(self):
        self.write("src/main.py", "abc")
        self.write("src/generated.py", "abcdefgh")
        self.write("tests/test.py", "test")
        self.write("notes.md", "notes")
        self.commit()
        report = self.payload("files", "--include", "src/*", "--include", "tests/*", "--exclude", "*generated*", "--sort", "size", "--limit", "1")
        self.assertEqual(report["files"][0]["path"], "tests/test.py")
        self.assertEqual(report["matching_files"], 2)
        self.assertEqual(report["total_files"], 4)
        self.assertEqual(report["total_bytes"], 7)
        self.assertTrue(report["truncated"])
        self.assertEqual(self.payload("files", "--include", "missing*")["matching_files"], 0)

    def test_source_context_clamps_to_blob_and_preserves_requested_range(self):
        self.write("a", "one\ntwo\nthree\nfour\nfive")
        self.commit()
        report = self.payload("source", "a", "--lines", "2:3", "--context", "1")
        self.assertEqual(report["content"], "one\ntwo\nthree\nfour\n")
        self.assertEqual(report["line_range"], "2:3")
        self.assertEqual(report["effective_line_range"], "1:4")
        self.assertEqual([r["number"] for r in report["lines"]], [1, 2, 3, 4])
        self.assertEqual(self.payload("source", "a", "--lines", "5:5", "--context", "20")["content"], "one\ntwo\nthree\nfour\nfive")
        self.assertEqual(self.cli("source", "a", "--context", "1").returncode, 1)

    def test_patch_can_preview_target_changes_since_merge_base(self):
        self.write("root")
        shared = self.commit()
        self.write("main")
        self.commit()
        self.git("checkout", "-b", "side", shared)
        self.write("side")
        self.commit()
        report = self.payload("patch", "main", "side", "--merge-base")
        self.assertEqual(report["resolved_a"], shared)
        self.assertNotEqual(report["input_a_resolved"], shared)
        self.assertIn("b/side", report["patch"])
        self.assertNotIn("b/main", report["patch"])
        self.assertTrue(report["merge_base"])

    def test_patch_copy_detection_reports_copy_provenance(self):
        content = "original content\n" * 20
        self.write("old", content)
        base = self.commit()
        self.write("new", content)
        self.commit()
        ordinary = self.payload("patch", base, "HEAD")
        self.assertIn("new file mode", ordinary["patch"])
        copied = self.payload("patch", base, "HEAD", "--find-copies")
        self.assertIn("copy from old", copied["patch"])
        self.assertIn("copy to new", copied["patch"])
        self.assertTrue(copied["find_copies"])

    def test_directory_activity_counts_commits_once_per_group(self):
        self.write("src/a.py")
        self.write("src/pkg/b.py")
        self.write("README")
        self.commit()
        self.write("src/a.py", "changed\n")
        self.commit(env={"GIT_AUTHOR_NAME": "Second", "GIT_AUTHOR_EMAIL": "second@example.test"})
        report = self.payload("directories")
        src = next(r for r in report["directories"] if r["path"] == "src")
        self.assertEqual((src["commits"], src["files"], src["authors"]), (2, 2, 2))
        detailed = self.payload("directories", "--depth", "2", "--sort", "path")
        self.assertEqual([r["path"] for r in detailed["directories"]], [".", "src", "src/pkg"])
        for flag in ("--csv", "--markdown", "--no-color"):
            self.assertEqual(self.cli("directories", flag).returncode, 0)
        self.assertFalse(self.payload("directories", "--max-commits", "1")["history_complete"])

    def test_inventory_groups_complete_tree_by_extension_or_directory(self):
        self.write("src/a.py", "abc")
        self.write("src/b.PY", "defgh")
        self.write("README", "x")
        self.commit()
        report = self.payload("inventory", "--limit", "1")
        self.assertEqual(report["total_entries"], 3)
        self.assertEqual(report["known_bytes"], 9)
        self.assertEqual(report["groups"][0]["group"], ".py")
        self.assertEqual(report["groups"][0]["known_bytes"], 8)
        self.assertEqual(report["groups"][0]["entries"], 2)
        grouped = self.payload("inventory", "src", "--group-by", "directory")
        self.assertEqual(grouped["groups"][0]["group"], "src")
        for flag in ("--csv", "--markdown", "--no-color"):
            self.assertEqual(self.cli("inventory", flag).returncode, 0)
        self.assertEqual(self.cli("inventory", "--author", "First").returncode, 2)

    def test_divergence_reports_unique_shared_and_ancestral_histories(self):
        self.write("root")
        shared = self.commit()
        self.write("main")
        self.commit()
        self.git("checkout", "-b", "side", shared)
        self.write("side")
        self.commit()
        report = self.payload("divergence", "main", "side")
        self.assertEqual(report["relationship"], "diverged")
        self.assertEqual(report["shared_commits"], 1)
        self.assertEqual([r["unique_commits"] for r in report["sides"]], [1, 1])
        self.assertEqual(report["merge_bases"], [shared])
        self.assertEqual(self.payload("divergence", shared, "side")["relationship"], "base-ancestor")
        self.assertEqual(self.payload("divergence", "side", shared)["relationship"], "target-ancestor")
        self.assertEqual(self.payload("divergence", "HEAD", "HEAD")["relationship"], "equal")
        for flag in ("--csv", "--markdown", "--no-color"):
            self.assertEqual(self.cli("divergence", "main", "side", flag).returncode, 0)
        self.assertEqual(self.cli("divergence", "main", "side", "--max-commits", "1").returncode, 2)
