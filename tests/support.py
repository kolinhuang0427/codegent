"""Real-repository fixtures for CLI regression coverage."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RepositoryCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-b", "main")
        self.git("config", "user.name", "First Author")
        self.git("config", "user.email", "first@example.test")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args, env=None):
        return subprocess.run(
            ["git", "-C", str(self.repo), *args], check=True,
            capture_output=True, text=True, env={**os.environ, **(env or {})},
        ).stdout.strip()

    def write(self, path, text="one\ntwo\nthree\n"):
        if os.name == "nt" and any(ord(char) < 32 for char in path):
            self.skipTest("Windows filenames cannot contain control characters")
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def commit(self, message="change", env=None):
        self.git("add", "-A")
        self.git("commit", "-m", message, env=env)
        return self.git("rev-parse", "HEAD")

    def cli(self, *args, env=None, cwd=None):
        return subprocess.run(
            [sys.executable, "-m", "codegent.main", "--repo", str(self.repo), *args],
            cwd=cwd or ROOT, env={**os.environ, "PYTHONPATH": str(ROOT), **(env or {})},
            capture_output=True, text=True,
        )

    def payload(self, *args):
        result = self.cli(*args, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)
