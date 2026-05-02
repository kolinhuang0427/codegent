from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class CodegentIntegrationTests(unittest.TestCase):
    def test_trace_follows_rename_and_outputs_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._init_repo(repo)
            (repo / "alpha.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
            self._commit(repo, "add alpha")
            run(["git", "mv", "alpha.py", "beta.py"], repo)
            (repo / "beta.py").write_text("def alpha():\n    return 2\n", encoding="utf-8")
            self._commit(repo, "rename alpha to beta")

            result = run(
                [
                    sys.executable,
                    "-m",
                    "codegent.main",
                    "trace",
                    "beta.py",
                    "--repo",
                    str(repo),
                    "--json",
                ],
                ROOT,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["total_commits"], 2)
            self.assertEqual(payload["commits"][0]["role"], "origin")
            self.assertTrue(payload["migrations"])

    def test_binary_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._init_repo(repo)
            (repo / "blob.bin").write_bytes(b"\x00\x01\x02\x03")
            self._commit(repo, "add binary")

            result = run(
                [
                    sys.executable,
                    "-m",
                    "codegent.main",
                    "bloodline",
                    "blob.bin",
                    "--repo",
                    str(repo),
                    "--json",
                ],
                ROOT,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["commits"][0]["binary"])

    def _init_repo(self, repo: Path) -> None:
        self.assertEqual(run(["git", "init"], repo).returncode, 0)
        self.assertEqual(run(["git", "config", "user.email", "test@example.com"], repo).returncode, 0)
        self.assertEqual(run(["git", "config", "user.name", "Test User"], repo).returncode, 0)

    def _commit(self, repo: Path, message: str) -> None:
        self.assertEqual(run(["git", "add", "-A"], repo).returncode, 0)
        result = run(["git", "commit", "-m", message], repo)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
