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
