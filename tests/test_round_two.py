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
