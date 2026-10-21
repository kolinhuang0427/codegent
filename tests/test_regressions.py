import json

from .support import RepositoryCase


class RegressionTests(RepositoryCase):
    def test_paths_resolve_from_repo_directory_and_allow_absolute_files(self):
        self.write("src/file.py")
        self.commit()
        result = self.payload("trace", "file.py", "--repo", str(self.repo / "src"))
        self.assertEqual(result["path"], "src/file.py")
        self.assertEqual(self.payload("trace", str(self.repo / "src/file.py"))["path"], "src/file.py")
        outside = self.cli("trace", str(self.repo.parent / "outside.py"))
        self.assertEqual(outside.returncode, 1)
        self.assertIn("outside the repository", outside.stderr)

    def test_diff_preserves_unusual_names_and_rename_stats(self):
        old, new = " old\t中文.py ", "new\nname.py"
        self.write(old)
        base = self.commit()
        self.git("mv", old, new)
        self.write(new, "one\ntwo\nthree\nfour\n")
        self.commit()
        item, = self.payload("diff", base, "HEAD")["files"]
        self.assertEqual(item["path"], new)
        self.assertEqual(item["renamed_from"], old)
        self.assertEqual(item["status"], "renamed")
        self.assertEqual(item["additions"], 1)

    def test_history_preserves_unusual_filenames_and_renames(self):
        old = " 中文 \told\n{a => b}.py "
        new = " 新 \tnew\n{b => c}.py "
        self.write(old)
        self.commit("original")
        self.git("mv", old, new)
        self.commit("rename")
        result = self.payload("trace", new)
        self.assertEqual(result["commits"][0]["files"], [old])
        self.assertEqual(result["migrations"], [[old, new]])
        self.assertEqual(result["commits"][1]["files"], [new])

    def test_git_pathspec_metacharacters_are_literal(self):
        self.write("[ab].py")
        self.commit("literal bracket filename")
        self.write("a.py")
        self.commit("different file")
        result = self.payload("trace", "[ab].py")
        self.assertEqual(result["total_commits"], 1)
        self.assertEqual(result["commits"][0]["message"], "literal bracket filename")

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
