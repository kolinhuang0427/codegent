from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from codegent.tracer import GitTracer, GitError
from .support import RepositoryCase, ROOT


class RoundThreeTests(RepositoryCase):
    pass

    def test_repository_root_with_a_trailing_newline_is_preserved(self):
        child = self.repo / "work\n"
        child.mkdir()
        def git(*args):
            return subprocess.run(["git", "-C", str(child), *args], check=True, capture_output=True, text=True).stdout
        git("init", "-b", "main")
        (child / "file.py").write_text("hello\n")
        git("add", "-A")
        git("-c", "user.name=Test", "-c", "user.email=test@example.test", "-c", "commit.gpgsign=false", "commit", "-m", "initial")
        report = self.payload("trace", "file.py", "--repo", str(child))
        self.assertEqual(report["total_commits"], 1)
        self.assertTrue(report["repo"].endswith("work\n"))

    def test_reachable_commit_api_normalizes_subdirectory_and_absolute_paths(self):
        self.write("src/[file].py")
        first = self.commit()
        self.write("outside.py")
        second = self.commit()
        tracer = GitTracer(str(self.repo / "src"))
        self.assertEqual(tracer.list_reachable_commits(path="[file].py"), [first])
        self.assertEqual(tracer.list_reachable_commits(path=str(self.repo / "src/[file].py")), [first])
        self.assertEqual(tracer.list_reachable_commits(), [first, second])

    def test_ownership_checks_blob_size_before_selecting_lines(self):
        self.write("file.py", "a reasonably long first line\nsecond\n")
        self.commit()
        rejected = self.cli("owners", "file.py", "--lines", "1:1", "--max-bytes", "8", "--json")
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("exceeds --max-bytes=8", json.loads(rejected.stderr)["error"])
        accepted = self.payload("owners", "file.py", "--max-bytes", "1024")
        self.assertEqual(accepted["selected_lines"], 2)
        self.assertEqual(accepted["size"], 36)

    def test_malformed_tree_blob_size_and_blame_records_are_structured_errors(self):
        import shlex
        import shutil
        self.write("file.py")
        self.commit()
        wrapper = self.repo / "wrapper"
        wrapper.mkdir()
        fake = wrapper / "git"
        real_git = shlex.quote(shutil.which("git"))
        cases = [(" ls-tree ", "broken", ("files",)),
                 (" cat-file -s ", "NaN", ("source", "file.py")),
                 (" blame ", "\tmissing header\n", ("owners", "file.py"))]
        for trigger, payload, arguments in cases:
            fake.write_text('#!/bin/sh\ncase " $* " in\n*"' + trigger + '"*) printf %s ' + shlex.quote(payload) + ';;\n*) exec ' + real_git + ' "$@";;\nesac\n')
            fake.chmod(0o755)
            result = self.cli(*arguments, "--json", env={"PATH": str(wrapper) + os.pathsep + os.environ["PATH"]})
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("cannot parse Git", json.loads(result.stderr)["error"])
            self.assertNotIn("Traceback", result.stderr)

    def test_markdown_author_exports_disclose_grouping_and_omitted_rows(self):
        self.write("file.py")
        self.commit()
        self.write("file.py", "changed\n")
        self.commit(env={"GIT_AUTHOR_NAME": "Second", "GIT_AUTHOR_EMAIL": "second@example.test"})
        result = self.cli("authors", "file.py", "--limit", "1", "--group-by", "email", "--markdown")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Showing 1 of 2 author groups", result.stdout)
        self.assertIn("omitted: 1", result.stdout)
        self.assertIn("Grouping: email", result.stdout)

    def test_unicode_runtime_and_argument_errors_survive_ascii_stderr(self):
        self.write("file.py")
        self.commit()
        result = self.cli("trace", "missing中文.py", env={"PYTHONIOENCODING": "ascii"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("no matching history", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        invalid = self.cli("trace", "file.py", "--wrong中文", env={"PYTHONIOENCODING": "ascii"})
        self.assertEqual(invalid.returncode, 2)
        self.assertNotIn("Traceback", invalid.stderr)
        self.assertIn("unrecognized arguments", invalid.stderr)

    def test_explicit_refs_work_when_the_checked_out_branch_is_unborn(self):
        self.write("file.py")
        first = self.commit()
        self.git("tag", "saved")
        self.git("checkout", "--orphan", "unborn")
        report = self.payload("trace", "file.py", "--ref", "saved")
        self.assertEqual(report["resolved_ref"], first)
        self.assertEqual(self.payload("diff", "saved", "saved")["files"], [])
        self.assertIsNone(self.payload("doctor")["head"])
        missing_head = self.cli("trace", "file.py", "--json")
        self.assertEqual(missing_head.returncode, 1)
        self.assertIn("invalid commit/ref", json.loads(missing_head.stderr)["error"])

    def test_refs_browses_lightweight_and_annotated_tags_with_limits(self):
        self.write("file.py")
        head = self.commit()
        self.git("tag", "v1")
        self.git("-c", "tag.gpgsign=false", "tag", "-a", "v2", "-m", "release")
        report = self.payload("refs", "--kind", "tag")
        self.assertEqual(report["total_refs"], 2)
        tags = {row["short_name"]: row for row in report["refs"]}
        self.assertEqual(tags["v1"]["object_id"], head)
        self.assertEqual(tags["v2"]["object_type"], "tag")
        self.assertEqual(tags["v2"]["peeled_object_id"], head)
        self.assertTrue(self.payload("refs", "--limit", "1")["truncated"])
        self.assertIn("# codegent refs", self.cli("refs", "--markdown").stdout)
