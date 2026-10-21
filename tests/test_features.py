from .support import RepositoryCase


class FeatureTests(RepositoryCase):
    def test_all_history_commands_accept_a_historical_ref(self):
        self.write("file.py")
        original = self.commit("original")
        self.write("file.py", "new\n")
        self.commit("new")
        for command in ("trace", "ancestry", "genemap", "bloodline"):
            result = self.payload(command, "file.py", "--ref", original)
            self.assertEqual(result["total_commits"], 1)
            self.assertEqual(result["requested_ref"], original)
