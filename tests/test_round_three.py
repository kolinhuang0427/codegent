from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from codegent.tracer import GitTracer, GitError
from .support import RepositoryCase, ROOT


class RoundThreeTests(RepositoryCase):
    pass

    def test_repository_root_with_a_trailing_newline_is_preserved(self):
        child = self.repo / "work\n"
        child.mkdir()
        def git(*args):
            return subprocess.run(["git", "-C", str(child), *args], check=True, capture_output=True, text=True).stdout
        git("init", "-b", "main")
        (child / "file.py").write_text("hello\n")
        git("add", "-A")
        git("-c", "user.name=Test", "-c", "user.email=test@example.test", "-c", "commit.gpgsign=false", "commit", "-m", "initial")
        report = self.payload("trace", "file.py", "--repo", str(child))
        self.assertEqual(report["total_commits"], 1)
        self.assertTrue(report["repo"].endswith("work\n"))

    def test_reachable_commit_api_normalizes_subdirectory_and_absolute_paths(self):
        self.write("src/[file].py")
        first = self.commit()
        self.write("outside.py")
        second = self.commit()
        tracer = GitTracer(str(self.repo / "src"))
        self.assertEqual(tracer.list_reachable_commits(path="[file].py"), [first])
        self.assertEqual(tracer.list_reachable_commits(path=str(self.repo / "src/[file].py")), [first])
        self.assertEqual(tracer.list_reachable_commits(), [first, second])

    def test_ownership_checks_blob_size_before_selecting_lines(self):
        self.write("file.py", "a reasonably long first line\nsecond\n")
        self.commit()
        rejected = self.cli("owners", "file.py", "--lines", "1:1", "--max-bytes", "8", "--json")
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("exceeds --max-bytes=8", json.loads(rejected.stderr)["error"])
        accepted = self.payload("owners", "file.py", "--max-bytes", "1024")
        self.assertEqual(accepted["selected_lines"], 2)
        self.assertEqual(accepted["size"], 36)

    def test_malformed_tree_blob_size_and_blame_records_are_structured_errors(self):
        import shlex
        import shutil
        self.write("file.py")
        self.commit()
        wrapper = self.repo / "wrapper"
        wrapper.mkdir()
        fake = wrapper / "git"
        real_git = shlex.quote(shutil.which("git"))
        cases = [(" ls-tree ", "broken", ("files",)),
                 (" cat-file -s ", "NaN", ("source", "file.py")),
                 (" blame ", "\tmissing header\n", ("owners", "file.py"))]
        for trigger, payload, arguments in cases:
            fake.write_text('#!/bin/sh\ncase " $* " in\n*"' + trigger + '"*) printf %s ' + shlex.quote(payload) + ';;\n*) exec ' + real_git + ' "$@";;\nesac\n')
            fake.chmod(0o755)
            result = self.cli(*arguments, "--json", env={"PATH": str(wrapper) + os.pathsep + os.environ["PATH"]})
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("cannot parse Git", json.loads(result.stderr)["error"])
            self.assertNotIn("Traceback", result.stderr)

    def test_markdown_author_exports_disclose_grouping_and_omitted_rows(self):
        self.write("file.py")
        self.commit()
        self.write("file.py", "changed\n")
        self.commit(env={"GIT_AUTHOR_NAME": "Second", "GIT_AUTHOR_EMAIL": "second@example.test"})
        result = self.cli("authors", "file.py", "--limit", "1", "--group-by", "email", "--markdown")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Showing 1 of 2 author groups", result.stdout)
        self.assertIn("omitted: 1", result.stdout)
        self.assertIn("Grouping: email", result.stdout)

    def test_unicode_runtime_and_argument_errors_survive_ascii_stderr(self):
        self.write("file.py")
        self.commit()
        result = self.cli("trace", "missing中文.py", env={"PYTHONIOENCODING": "ascii"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("no matching history", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        invalid = self.cli("trace", "file.py", "--wrong中文", env={"PYTHONIOENCODING": "ascii"})
        self.assertEqual(invalid.returncode, 2)
        self.assertNotIn("Traceback", invalid.stderr)
        self.assertIn("unrecognized arguments", invalid.stderr)

    def test_explicit_refs_work_when_the_checked_out_branch_is_unborn(self):
        self.write("file.py")
        first = self.commit()
        self.git("tag", "saved")
        self.git("checkout", "--orphan", "unborn")
        report = self.payload("trace", "file.py", "--ref", "saved")
        self.assertEqual(report["resolved_ref"], first)
        self.assertEqual(self.payload("diff", "saved", "saved")["files"], [])
        self.assertIsNone(self.payload("doctor")["head"])
        missing_head = self.cli("trace", "file.py", "--json")
        self.assertEqual(missing_head.returncode, 1)
        self.assertIn("invalid commit/ref", json.loads(missing_head.stderr)["error"])

    def test_refs_browses_lightweight_and_annotated_tags_with_limits(self):
        self.write("file.py")
        head = self.commit()
        self.git("tag", "v1")
        self.git("-c", "tag.gpgsign=false", "tag", "-a", "v2", "-m", "release")
        report = self.payload("refs", "--kind", "tag")
        self.assertEqual(report["total_refs"], 2)
        tags = {row["short_name"]: row for row in report["refs"]}
        self.assertEqual(tags["v1"]["object_id"], head)
        self.assertEqual(tags["v2"]["object_type"], "tag")
        self.assertEqual(tags["v2"]["peeled_object_id"], head)
        self.assertTrue(self.payload("refs", "--limit", "1")["truncated"])
        self.assertIn("# codegent refs", self.cli("refs", "--markdown").stdout)

    def test_commit_ranges_exclude_base_and_support_path_and_presentation_filters(self):
        self.write("a.py")
        base = self.commit("base")
        self.write("a.py", "second\n")
        self.commit("second")
        self.write("b.py")
        head = self.commit("third")
        report = self.payload("commits", base, "HEAD", "--newest-first")
        self.assertEqual([row["message"] for row in report["commits"]], ["third", "second"])
        self.assertEqual(report["resolved_ref"], head)
        self.assertTrue(report["range_complete"])
        self.assertEqual(self.payload("commits", base, "HEAD", "--path", "a.py")["total_commits"], 1)
        self.assertEqual(self.payload("commits", "HEAD", "HEAD")["commits"], [])
        self.git("branch", "unicode\u2028branch")
        self.assertIn("unicode\u2028branch", [row["short_name"] for row in self.payload("refs")["refs"]])

    def test_patch_preview_scopes_paths_context_size_and_markdown_fences(self):
        self.write("a.py", "old\n")
        self.write("b.py", "other\n")
        base = self.commit()
        self.write("a.py", "new ``` content\n")
        self.write("b.py", "changed elsewhere\n")
        self.commit()
        report = self.payload("patch", base, "HEAD", "--path", "a.py", "--context", "0")
        self.assertIn("+new ``` content", report["patch"])
        self.assertNotIn("b.py", report["patch"])
        self.assertEqual(report["context"], 0)
        rejected = self.cli("patch", base, "HEAD", "--max-bytes", "3", "--json")
        self.assertIn("patch output exceeds", json.loads(rejected.stderr)["error"])
        markdown = self.cli("patch", base, "HEAD", "--markdown")
        self.assertIn("````diff", markdown.stdout)
        self.assertIn("# codegent patch", markdown.stdout)

    def test_timeline_can_distinguish_author_and_committer_dates(self):
        self.write("file.py")
        self.commit(env={"GIT_AUTHOR_DATE": "2026-01-01T12:00:00Z", "GIT_COMMITTER_DATE": "2026-03-01T12:00:00Z"})
        self.write("file.py", "changed\n")
        self.commit(env={"GIT_AUTHOR_DATE": "2026-02-01T12:00:00Z", "GIT_COMMITTER_DATE": "2026-03-02T12:00:00Z"})
        authored = self.payload("timeline")
        committed = self.payload("timeline", "--date-basis", "committer")
        self.assertEqual([row["period"] for row in authored["periods"]], ["2026-01", "2026-02"])
        self.assertEqual([row["period"] for row in committed["periods"]], ["2026-03"])
        self.assertEqual(committed["periods"][0]["commits"], 2)
        self.assertIn("committer_date", self.payload("trace", "file.py")["commits"][0])

    def test_timeline_fills_observed_gaps_with_budget(self):
        self.write("a")
        self.commit(env={"GIT_AUTHOR_DATE": "2024-01-01T00:00:00Z"})
        self.write("a", "changed\n")
        self.commit(env={"GIT_AUTHOR_DATE": "2024-03-01T00:00:00Z"})
        report = self.payload("timeline", "--fill-gaps")
        self.assertEqual([r["period"] for r in report["periods"]], ["2024-01", "2024-02", "2024-03"])
        self.assertEqual(report["periods"][1]["commits"], 0)
        self.assertEqual(len(self.payload("timeline")["periods"]), 2)
        result = self.cli("timeline", "--fill-gaps", "--max-periods", "2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("max-periods", result.stderr)
        for period in ("day", "year"):
            self.assertTrue(self.payload("timeline", "--fill-gaps", "--period", period)["fill_gaps"])

    def test_file_size_sort_precedes_limit(self):
        self.write("a", "small")
        self.write("b", "larger content")
        self.write("c", "small")
        self.commit()
        report = self.payload("files", "--sort", "size", "--limit", "1")
        self.assertEqual(report["files"][0]["path"], "b")
        self.assertEqual(report["total_files"], 3)
        self.assertEqual(report["total_bytes"], 24)
        self.assertTrue(report["truncated"])
        self.assertEqual([r["path"] for r in self.payload("files", "--sort", "size")["files"]], ["b", "a", "c"])
        self.assertEqual([r["path"] for r in self.payload("files")["files"]], ["a", "b", "c"])

    def test_file_kind_filters_git_modes(self):
        self.write("plain", "plain\n")
        self.write("run", "run\n")
        os.chmod(self.repo / "run", 0o755)
        os.symlink("plain", self.repo / "link")
        tip = self.commit()
        self.git("update-index", "--add", "--cacheinfo", f"160000,{tip},module")
        self.git("commit", "-m", "add gitlink")
        for kind, expected in (("file", "plain"), ("executable", "run"), ("symlink", "link"), ("submodule", "module")):
            report = self.payload("files", "--kind", kind)
            self.assertEqual([r["path"] for r in report["files"]], [expected])
            self.assertEqual(report["total_files"], 4)
            self.assertEqual(report["matching_files"], 1)
            self.assertEqual(report["unknown_size_entries"], int(kind == "submodule"))
            self.assertEqual(self.cli("files", "--kind", kind, "--markdown").returncode, 0)

    def test_blame_cross_file_copy_attribution(self):
        content = "".join(f"original_function_{n} = original_implementation_value_{n}\n" for n in range(20))
        self.write("original.py", content)
        original = self.commit("original")
        self.write("copy.py", content)
        copied = self.commit("copy", env={"GIT_AUTHOR_NAME": "Copy Author", "GIT_AUTHOR_EMAIL": "copy@example.test"})
        default = self.payload("owners", "copy.py")
        self.assertEqual(default["owners"][0]["commits"], [copied])
        detected = self.payload("owners", "copy.py", "--detect-copies")
        self.assertEqual(detected["owners"][0]["commits"], [original])
        self.assertTrue(detected["detect_copies"])
        self.assertFalse(detected["detect_moves"])

    def test_ownership_can_group_surviving_lines_by_commit(self):
        self.write("a", "first line\n")
        first = self.commit("first")
        self.write("a", "first line\nsecond line\n")
        second = self.commit("second")
        self.assertEqual(len(self.payload("owners", "a")["owners"]), 1)
        report = self.payload("owners", "a", "--group-by", "commit")
        self.assertEqual({r["commit"] for r in report["owners"]}, {first, second})
        self.assertEqual([r["lines"] for r in report["owners"]], [1, 1])
        self.assertEqual(sum(r["percentage"] for r in report["owners"]), 100)
        for flag in ("--markdown", "--no-color"):
            result = self.cli("owners", "a", "--group-by", "commit", flag)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(first, result.stdout)

    def test_csv_preserves_quoting_nested_metadata_and_empty_tables(self):
        name = '新, "quoted"\nfile'
        self.write(name, "one\ntwo\n")
        base = self.commit('message, "quoted"')
        result = self.cli("files", "--csv")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = list(csv.DictReader(io.StringIO(result.stdout)))
        self.assertEqual(rows[0]["path"], name)
        self.assertEqual(json.loads(rows[0]["report_metadata"])["resolved_ref"], base)
        history = self.cli("trace", name, "--csv")
        row = list(csv.DictReader(io.StringIO(history.stdout)))[0]
        self.assertEqual(row["message"], 'message, "quoted"')
        self.assertEqual(json.loads(row["files"]), [name])
        empty = self.cli("commits", base, base, "--csv")
        row = list(csv.DictReader(io.StringIO(empty.stdout)))[0]
        self.assertEqual(row["row_present"], "false")
        self.assertEqual(json.loads(row["report_metadata"])["total_commits"], 0)
        target = self.repo / "out.csv"
        self.assertEqual(self.cli("files", "--csv", "--output", str(target)).returncode, 0)
        self.assertIn(name, list(csv.DictReader(io.StringIO(target.read_text())))[0]["path"])
        conflict = self.cli("--csv", "files", "--markdown")
        self.assertEqual(conflict.returncode, 2)

    def test_all_commands_offer_csv_rows(self):
        self.write("a")
        base = self.commit()
        self.write("a", "one\ntwo\nthree\nfour\n")
        self.commit()
        for command in ("trace", "ancestry", "genemap", "bloodline", "diff", "authors", "hotspots", "owners", "timeline", "cochange", "files", "source", "doctor", "refs", "commits", "patch"):
            args = [command, base, "HEAD"] if command in {"diff", "commits", "patch"} else [command] if command in {"hotspots", "timeline", "files", "doctor", "refs"} else [command, "a"]
            for extra in ([[] , ["--summary"]] if command == "diff" else [[]]):
                result = self.cli(*args, *extra, "--csv")
                self.assertEqual(result.returncode, 0, result.stderr)
                rows = list(csv.DictReader(io.StringIO(result.stdout)))
                self.assertTrue(rows)
                self.assertIn("report_metadata", rows[0])
                json.loads(rows[0]["report_metadata"])

    def test_csv_quotes_carriage_returns_in_raw_output(self):
        name = "carriage\rreturn.txt"
        self.write(name)
        self.commit()
        result = subprocess.run([sys.executable, "-m", "codegent.main", "--repo", str(self.repo), "files", "--csv"], cwd=ROOT, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = list(csv.DictReader(io.StringIO(result.stdout.decode("utf-8"), newline="")))
        self.assertEqual(rows[0]["path"], name)
