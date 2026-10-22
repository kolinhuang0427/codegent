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
