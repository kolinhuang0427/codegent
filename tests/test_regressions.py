import json

from .support import RepositoryCase


class RegressionTests(RepositoryCase):
    def test_missing_git_is_a_readable_error(self):
        result = self.cli("trace", "file.py", "--json", env={"PATH": str(self.repo)})
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot run git", json.loads(result.stderr)["error"])
        self.assertNotIn("Traceback", result.stderr)
