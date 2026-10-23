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
