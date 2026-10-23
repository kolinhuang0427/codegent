import json
import subprocess
import sys

from .support import RepositoryCase, ROOT


class FeatureTests(RepositoryCase):
    def test_package_module_entrypoint_exposes_version_and_commands(self):
        result = subprocess.run([sys.executable, "-m", "codegent", "--version"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "codegent 0.4.0")
        help_result = subprocess.run([sys.executable, "-m", "codegent", "--help"], cwd=ROOT, capture_output=True, text=True)
        self.assertIn("hotspots", help_result.stdout)

    def test_markdown_export_escapes_repository_content(self):
        self.write("file.py")
        self.commit("fix | <script>alert(1)</script>")
        result = self.cli("trace", "file.py", "--markdown")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# codegent trace", result.stdout)
        self.assertIn("\\| &lt;script&gt;", result.stdout)
        self.assertNotIn("<script>", result.stdout)
        self.assertNotIn("\x1b", result.stdout)
        for command in ("authors", "owners"):
            self.assertEqual(self.cli(command, "file.py", "--markdown").returncode, 0)

    def test_file_export_is_atomic_and_errors_preserve_existing_reports(self):
        self.write("file.py")
        self.commit()
        target = self.repo / "report.json"
        target.write_text("previous")
        result = self.cli("trace", "file.py", "--json", "--output", str(target))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        saved = target.read_text()
        self.assertEqual(json.loads(saved)["total_commits"], 1)
        failed = self.cli("trace", "file.py", "--ref", "missing", "--output", str(target))
        self.assertEqual(failed.returncode, 1)
        self.assertEqual(target.read_text(), saved)
        missing_dir = self.cli("trace", "file.py", "--output", str(self.repo / "missing/report"))
        self.assertIn("cannot write report", missing_dir.stderr)

    def test_diff_summary_counts_text_binary_and_statuses(self):
        self.write("old.py", "old\n")
        base = self.commit()
        self.git("rm", "old.py")
        self.write("new.py", "new\nnewer\n")
        (self.repo / "binary.dat").write_bytes(b"\0binary")
        self.commit()
        result = self.payload("diff", base, "HEAD", "--summary")
        summary = result["summary"]
        self.assertEqual(summary["files"], 3)
        self.assertEqual(summary["additions"], 2)
        self.assertEqual(summary["deletions"], 1)
        self.assertEqual(summary["binary_files"], 1)
        self.assertEqual(summary["statuses"], {"added": 2, "deleted": 1})

    def test_diff_path_filters_are_literal_and_repeatable(self):
        self.write("src/[ab].py")
        self.write("other.py")
        base = self.commit()
        self.write("src/[ab].py", "changed\n")
        self.write("other.py", "other changed\n")
        self.commit()
        report = self.payload("diff", base, "HEAD", "--path", "src/[ab].py")
        self.assertEqual([row["path"] for row in report["files"]], ["src/[ab].py"])
        both = self.payload("diff", base, "HEAD", "--path", "src", "--path", "other.py")
        self.assertEqual(len(both["files"]), 2)

    def test_owners_reports_surviving_lines_at_a_committed_ref(self):
        self.write("file.py")
        original = self.commit()
        self.write("file.py", "one\nSECOND\nthree\n")
        self.commit(env={"GIT_AUTHOR_NAME": "Second", "GIT_AUTHOR_EMAIL": "second@example.test"})
        self.write("file.py", "uncommitted\n")
        report = self.payload("owners", "file.py")
        self.assertEqual([row["lines"] for row in report["owners"]], [2, 1])
        selected = self.payload("owners", "file.py", "--lines", "2:2")
        self.assertEqual(selected["owners"][0]["percentage"], 100)
        self.assertIn("Second", selected["owners"][0]["author"])
        self.assertEqual(len(self.payload("owners", "file.py", "--ref", original)["owners"]), 1)

    def test_hotspots_aggregate_per_file_and_support_directory_scope(self):
        self.write("src/hot.py", "one\n")
        self.write("cold.py", "cold\n")
        self.commit()
        self.write("src/hot.py", "one\ntwo\n")
        self.commit()
        report = self.payload("hotspots", "--min-commits", "2")
        self.assertEqual([row["path"] for row in report["files"]], ["src/hot.py"])
        self.assertEqual(report["files"][0]["commits"], 2)
        self.assertEqual(report["files"][0]["additions"], 2)
        self.assertEqual(self.payload("hotspots", "src")["matching_files"], 1)
        self.assertEqual(self.payload("hotspots", "missing")["files"], [])

    def test_author_report_aggregates_multiple_commits_per_identity(self):
        self.write("file.py", "one\n")
        self.commit()
        self.write("file.py", "one\ntwo\n")
        self.commit()
        self.write("file.py", "one\ntwo\nthree\n")
        self.commit(env={"GIT_AUTHOR_NAME": "Second", "GIT_AUTHOR_EMAIL": "second@example.test"})
        result = self.payload("authors", "file.py")
        self.assertEqual(result["total_authors"], 2)
        self.assertEqual(result["authors"][0]["commits"], 2)
        self.assertEqual(result["authors"][0]["additions"], 2)
        limited = self.payload("authors", "file.py", "--limit", "1", "--sort", "churn")
        self.assertEqual(len(limited["authors"]), 1)

    def test_mailmap_merges_author_aliases(self):
        self.write("file.py")
        self.commit("alias", env={"GIT_AUTHOR_NAME": "Alias", "GIT_AUTHOR_EMAIL": "alias@example.test"})
        self.write("file.py", "changed\n")
        self.write(".mailmap", "First Author <first@example.test> Alias <alias@example.test>\n")
        self.commit("canonical")
        self.assertEqual(self.payload("bloodline", "file.py")["genetic_diversity"], 2)
        mapped = self.payload("bloodline", "file.py", "--mailmap")
        self.assertEqual(mapped["genetic_diversity"], 1)
        self.assertTrue(mapped["mailmap"])

    def test_whitespace_only_diff_can_be_ignored(self):
        self.write("file.py", "x = 1\n")
        base = self.commit()
        self.write("file.py", "x    =    1\n")
        self.commit()
        self.assertEqual(len(self.payload("diff", base, "HEAD")["files"]), 1)
        self.assertEqual(self.payload("diff", base, "HEAD", "--ignore-whitespace")["files"], [])
        history = self.payload("trace", "file.py", "--ignore-whitespace")
        self.assertTrue(history["selection"]["ignore_whitespace"])

    def test_rename_similarity_is_configurable_for_history_and_diff(self):
        self.write("old.py", "".join(f"line {i}\n" for i in range(10)))
        base = self.commit()
        self.git("mv", "old.py", "new.py")
        self.write("new.py", "".join(f"line {i}\n" for i in range(7)) + "changed a\nchanged b\nchanged c\n")
        self.commit()
        permissive = self.payload("trace", "new.py", "--rename-threshold", "30")
        strict = self.payload("trace", "new.py", "--rename-threshold", "100")
        self.assertEqual(permissive["total_commits"], 2)
        self.assertEqual(strict["total_commits"], 1)
        self.assertEqual(len(self.payload("diff", base, "HEAD", "--rename-threshold", "100")["files"]), 2)

    def test_first_parent_excludes_side_branch_commits(self):
        self.write("file.py")
        self.commit("base")
        self.git("checkout", "-b", "feature")
        self.write("file.py", "feature\n")
        feature = self.commit("side branch")
        self.git("checkout", "main")
        self.write("other.py")
        self.commit("main work")
        self.git("merge", "--no-ff", "feature", "-m", "integrate")
        result = self.payload("trace", "file.py", "--first-parent")
        self.assertNotIn(feature, [c["hash"] for c in result["commits"]])
        self.assertTrue(result["selection"]["first_parent"])

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
