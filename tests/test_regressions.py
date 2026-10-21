import json

from .support import RepositoryCase


class RegressionTests(RepositoryCase):
    def test_refs_are_single_commits_and_disambiguated_from_paths(self):
        self.write("file.py")
        self.write("main")
        self.commit()
        self.assertEqual(self.payload("diff", "main", "HEAD")["files"], [])
        result = self.cli("trace", "file.py", "main..HEAD", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("invalid commit/ref", json.loads(result.stderr)["error"])

    def test_nonpositive_limit_does_not_disable_history_bound(self):
        for limit in ("0", "-1"):
            result = self.cli("trace", "file.py", "--max-commits", limit)
            self.assertEqual(result.returncode, 2)
            self.assertIn("greater than zero", result.stderr)

    def test_missing_git_is_a_readable_error(self):
        result = self.cli("trace", "file.py", "--json", env={"PATH": str(self.repo)})
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot run git", json.loads(result.stderr)["error"])
        self.assertNotIn("Traceback", result.stderr)
