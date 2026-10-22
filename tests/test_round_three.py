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
