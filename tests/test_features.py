from .support import RepositoryCase


class FeatureTests(RepositoryCase):
    def test_date_window_selects_commits_and_discloses_partial_history(self):
        self.write("file.py")
        self.commit("January", env={"GIT_AUTHOR_DATE": "2026-01-01T12:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T12:00:00Z"})
        self.write("file.py", "February\n")
        self.commit("February", env={"GIT_AUTHOR_DATE": "2026-02-01T12:00:00Z", "GIT_COMMITTER_DATE": "2026-02-01T12:00:00Z"})
        result = self.payload("trace", "file.py", "--since", "2026-01-15", "--until", "2026-03-01")
        self.assertEqual([c["message"] for c in result["commits"]], ["February"])
        self.assertFalse(result["origin_confirmed"])
        invalid = self.cli("trace", "file.py", "--since", "nonsense")
        self.assertIn("invalid ISO date", invalid.stderr)

    def test_all_history_commands_accept_a_historical_ref(self):
        self.write("file.py")
        original = self.commit("original")
        self.write("file.py", "new\n")
        self.commit("new")
        for command in ("trace", "ancestry", "genemap", "bloodline"):
            result = self.payload(command, "file.py", "--ref", original)
            self.assertEqual(result["total_commits"], 1)
            self.assertEqual(result["requested_ref"], original)
