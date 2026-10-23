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
        self.assertEqual(self.cli("--merges", "timeline", "--no-merges").returncode, 0)
