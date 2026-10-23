from .support import RepositoryCase


class FeatureTests(RepositoryCase):
    def test_no_follow_stops_before_the_previous_filename(self):
        self.write("old.py")
        self.commit()
        self.git("mv", "old.py", "new.py")
        self.commit()
        result = self.payload("trace", "new.py", "--no-follow")
        self.assertEqual(result["total_commits"], 1)
        self.assertFalse(result["followed_renames"])
        self.assertIn("Follows renames: no", self.cli("trace", "new.py", "--no-follow").stdout)

    def test_author_filter_is_literal_and_marks_the_selection(self):
        self.write("file.py")
        self.commit("first")
        self.write("file.py", "second\n")
        self.commit("second", env={"GIT_AUTHOR_NAME": "Second [Author]", "GIT_AUTHOR_EMAIL": "second@example.test"})
        result = self.payload("trace", "file.py", "--author", "[Author]")
        self.assertEqual(result["total_commits"], 1)
        self.assertEqual(result["latest"]["message"], "second")
        self.assertFalse(result["origin_confirmed"])

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
