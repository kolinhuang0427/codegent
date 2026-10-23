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
