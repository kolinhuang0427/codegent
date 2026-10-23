import json
import subprocess

from .support import RepositoryCase


class RegressionTests(RepositoryCase):
    def test_argument_errors_are_json_and_unsupported_options_are_rejected(self):
        for arguments in (("--json",), ("trace", "file.py", "--max-commits", "0", "--json"),
                          ("--json", "trace", "file.py", "--markdown"),
                          ("diff", "HEAD", "HEAD", "--since", "2026-01-01", "--json")):
            result = self.cli(*arguments)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("error", json.loads(result.stderr))
            self.assertEqual(result.stdout, "")

    def test_closed_stdout_pipe_exits_without_a_traceback(self):
        import sys
        from .support import ROOT
        self.write("file.py")
        self.commit()
        process = subprocess.Popen([sys.executable, "-m", "codegent", "trace", "file.py", "--repo", str(self.repo)],
                                   cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        process.stdout.close()
        stderr = process.stderr.read()
        process.stderr.close()
        self.assertEqual(process.wait(timeout=10), 0, stderr)
        self.assertNotIn("Traceback", stderr)

    def test_non_utf8_terminal_gets_a_readable_export_suggestion(self):
        self.write("中文.py")
        self.commit()
        result = self.cli("trace", "中文.py", env={"PYTHONIOENCODING": "ascii"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("UTF-8 terminal or --output", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_empty_and_binary_ownership_and_signature_configuration(self):
        self.write("empty.py", "")
        (self.repo / "binary.dat").write_bytes(b"\0binary")
        self.commit()
        self.git("config", "log.showSignature", "true")
        self.git("config", "color.ui", "always")
        self.assertEqual(self.payload("trace", "empty.py")["total_commits"], 1)
        self.assertEqual(self.payload("owners", "empty.py")["owners"], [])
        result = self.cli("owners", "binary.dat", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("binary", json.loads(result.stderr)["error"])

    def test_wide_and_combining_text_fits_boxes_and_no_color_presence_is_respected(self):
        import unicodedata
        self.write("file.py")
        self.commit("说明" * 100, env={"GIT_AUTHOR_NAME": "维护者" + "A\u0301" * 100})
        result = self.cli("trace", "file.py", env={"NO_COLOR": "", "CLICOLOR_FORCE": "1"})
        self.assertNotIn("\x1b", result.stdout)
        boxes = [line for line in result.stdout.splitlines() if line.lstrip().startswith(("╭", "│", "╰"))]
        widths = [sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in line) for line in boxes]
        self.assertTrue(boxes)
        self.assertEqual(set(widths), {78})

    def test_repository_control_characters_are_inert_in_text_and_preserved_in_json(self):
        name = "file\x1b[2J.py"
        self.write(name)
        self.commit("subject \x1b[2J")
        result = self.cli("trace", name, "--no-color")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("\x1b", result.stdout)
        self.assertIn("\\x1b[2J", result.stdout)
        self.assertEqual(self.payload("trace", name)["path"], name)

    def test_git_timeout_is_bounded_and_readable(self):
        fake_git = self.repo / "git"
        fake_git.write_text("#!/bin/sh\nexec /bin/sleep 5\n")
        fake_git.chmod(0o755)
        result = self.cli("trace", "file.py", "--timeout", "0.05", "--json", env={"PATH": str(self.repo)})
        self.assertEqual(result.returncode, 1)
        self.assertIn("timed out", json.loads(result.stderr)["error"])
        invalid = self.cli("trace", "file.py", "--timeout", "nan")
        self.assertIn("positive finite", invalid.stderr)

    def test_shallow_and_limited_history_do_not_claim_a_confirmed_origin(self):
        self.write("file.py")
        self.commit("first")
        self.write("file.py", "second\n")
        self.commit("second")
        limited = self.payload("bloodline", "file.py", "--max-commits", "1")
        self.assertFalse(limited["origin_confirmed"])
        self.assertEqual(limited["origin"]["role"], "boundary")
        clone = self.repo.parent / (self.repo.name + "-shallow")
        import shutil
        self.addCleanup(shutil.rmtree, clone, True)
        subprocess.run(["git", "clone", "--depth=1", self.repo.as_uri(), str(clone)], check=True, capture_output=True)
        result = self.payload("ancestry", "file.py", "--repo", str(clone))
        blame = self.payload("owners", "file.py", "--repo", str(clone))
        self.assertTrue(blame["shallow"])
        self.assertTrue(blame["warnings"])
        self.assertGreater(blame["owners"][0]["boundary_lines"], 0)
        self.assertTrue(result["shallow"])
        self.assertFalse(result["history_complete"])
        self.assertIn("Shallow", " ".join(result["warnings"]))

    def test_ancestry_uses_each_historical_filename(self):
        self.write("old.py")
        self.commit("original")
        self.git("mv", "old.py", "middle.py")
        self.commit("first rename")
        self.git("mv", "middle.py", "new.py")
        self.commit("second rename")
        result = self.payload("ancestry", "new.py")
        self.assertEqual([g["path"] for g in result["genes"]], ["old.py", "middle.py", "new.py"])

    def test_truncation_requires_an_additional_matching_commit(self):
        self.write("file.py")
        self.commit("first")
        self.write("file.py", "changed\n")
        self.commit("second")
        self.assertFalse(self.payload("trace", "file.py", "--max-commits", "2")["truncated"])
        limited = self.payload("trace", "file.py", "--max-commits", "1")
        self.assertTrue(limited["truncated"])
        self.assertEqual(limited["total_commits"], 1)
        self.assertEqual(limited["latest"]["message"], "second")

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
