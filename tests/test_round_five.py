"""Real-repository coverage for maintainer report refinements."""
import csv
import io
import json
import unittest
from codegent.display import display_width, truncate_cells
from tests.support import RepositoryCase


class MaintainerRefinements(RepositoryCase):

    def test_neutral_supplementary_symbols_keep_their_width(self):
        self.assertEqual(display_width("🜀abcd"), 5)
        self.assertEqual(truncate_cells("🜀abcd", 5), "🜀abcd")
        self.assertEqual(display_width("🇨🇦"), 2)
        self.write("a")
        self.commit("🜀abcd")
        result = self.cli("trace", "a", "--no-color")
        rows = [line for line in result.stdout.splitlines() if line.startswith(("  ╭", "  │", "  ╰"))]
        self.assertEqual(len({display_width(line) for line in rows}), 1)

    def test_standalone_skin_tone_does_not_consume_ascii_width(self):
        self.assertEqual(display_width("A🏽"), 3)
        self.assertEqual(display_width("👍🏽"), 2)
        self.assertEqual(display_width("🚀🏽"), 4)
        self.assertEqual(display_width("☝️🏽"), 2)
        self.assertEqual(truncate_cells("A🏽abcd", 6), "A🏽...")
        self.write("a")
        self.commit("A🏽")
        result = self.cli("trace", "a", "--no-color")
        rows = [line for line in result.stdout.splitlines() if line.startswith(("  ╭", "  │", "  ╰"))]
        self.assertEqual(len({display_width(line) for line in rows}), 1)

    def test_empty_line_ranges_are_rejected_instead_of_selecting_whole_file(self):
        self.write("a")
        self.commit()
        for command in ("source", "owners"):
            result = self.cli(command, "a", "--lines", "", "--json")
            self.assertEqual(result.returncode, 1)
            self.assertIn("START:END", json.loads(result.stderr)["error"])
            self.assertEqual(self.payload(command, "a")["file_lines"], 3)

    def test_cochange_directory_scope_excludes_its_own_children(self):
        self.write("src/a")
        self.write("src/b")
        self.write("src2/outside")
        self.commit()
        report = self.payload("cochange", "src")
        self.assertEqual(report["target_commits"], 1)
        self.assertEqual([r["path"] for r in report["files"]], ["src2/outside"])
        self.assertEqual(self.payload("cochange", ".")["files"], [])

    def test_cochange_exclusions_keep_the_target_denominator(self):
        for path in ("target", "generated/a", "docs/a", "keep"):
            self.write(path)
        self.commit()
        report = self.payload("cochange", "target", "--exclude", "generated/*", "--exclude", "docs/*", "--limit", "1")
        self.assertEqual(report["target_commits"], 1)
        self.assertEqual(report["matching_files"], 1)
        self.assertEqual(report["files"][0]["path"], "keep")
        self.assertEqual(report["files"][0]["fraction"], 1)

    def test_cochange_minimum_fraction_and_invalid_bounds(self):
        self.write("target")
        self.write("companion")
        self.commit()
        self.write("target", "changed")
        self.commit()
        self.assertEqual(self.payload("cochange", "target", "--min-fraction", "0.5")["matching_files"], 1)
        self.assertEqual(self.payload("cochange", "target", "--min-fraction", "0.50001")["matching_files"], 0)
        for value in ("nan", "inf", "-0.1", "1.1"):
            self.assertEqual(self.cli("cochange", "target", "--min-fraction", value).returncode, 2)

    def test_jaccard_discounts_frequently_changed_companions(self):
        for path in ("target", "a-busy", "z-focused"):
            self.write(path)
        self.commit()
        self.write("a-busy", "unrelated edit")
        self.commit()
        report = self.payload("cochange", "target", "--sort", "jaccard")
        self.assertEqual([r["path"] for r in report["files"]], ["z-focused", "a-busy"])
        self.assertEqual([r["jaccard"] for r in report["files"]], [1, 0.5])
        self.assertEqual(report["files"][1]["candidate_commits"], 2)
        for fmt in ("--markdown", "--csv", "--no-color"):
            self.assertIn("jaccard", self.cli("cochange", "target", fmt).stdout.lower())

    def test_hotspot_inclusions_are_or_combined_before_exclusions(self):
        for path in ("src/a.py", "tests/a.py", "src/vendor.py", "docs/readme"):
            self.write(path)
        self.commit()
        report = self.payload("hotspots", "--include", "src/*", "--include", "tests/*", "--exclude", "*vendor*", "--limit", "1")
        self.assertEqual(report["matching_files"], 2)
        self.assertEqual(report["files"][0]["path"], "src/a.py")
        self.assertEqual(report["includes"], ["src/*", "tests/*"])

    def test_hotspot_churn_threshold_is_inclusive_and_binary_is_unknown(self):
        self.write("small", "one\n")
        self.write("large", "one\ntwo\nthree\n")
        (self.repo / "binary").write_bytes(b"\0data")
        self.commit()
        report = self.payload("hotspots", "--min-churn", "3")
        self.assertEqual([r["path"] for r in report["files"]], ["large"])
        self.assertEqual(report["min_churn"], 3)
        self.assertEqual(self.payload("hotspots", "--min-churn", "0")["matching_files"], 3)
        self.assertEqual(self.cli("hotspots", "--min-churn", "-1").returncode, 2)

    def test_directory_exclusions_apply_to_files_before_aggregation(self):
        self.write("src/a", "one\n")
        self.write("src/generated/b", "one\ntwo\nthree\n")
        self.write("docs/a")
        self.commit()
        report = self.payload("directories", "--exclude", "src/generated/*", "--exclude", "docs/*")
        self.assertEqual(report["total_directories"], 1)
        self.assertEqual(report["directories"][0]["churn"], 1)
        self.assertEqual(report["directories"][0]["files"], 1)

    def test_directory_minimum_commits_precedes_limit(self):
        self.write("busy/a")
        self.write("once/a")
        self.commit()
        self.write("busy/a", "changed")
        self.commit()
        report = self.payload("directories", "--min-commits", "2", "--limit", "1")
        self.assertEqual(report["total_directories"], 2)
        self.assertEqual(report["matching_directories"], 1)
        self.assertEqual(report["directories"][0]["path"], "busy")
        self.assertIn("matching directories", self.cli("directories", "--min-commits", "2", "--markdown").stdout)

    def test_directory_author_and_file_rankings(self):
        self.write("a/a")
        self.write("z/a")
        self.write("z/b")
        self.commit()
        self.write("z/a", "changed")
        self.commit(env={"GIT_AUTHOR_NAME": "Second", "GIT_AUTHOR_EMAIL": "second@example.test"})
        for metric in ("authors", "files"):
            report = self.payload("directories", "--sort", metric, "--limit", "1")
            self.assertEqual(report["directories"][0]["path"], "z")
            self.assertEqual(report["directories"][0][metric], 2)

    def test_inventory_filters_select_objects_before_grouping(self):
        self.write("src/a.py", "abc")
        self.write("src/skip.py", "abcd")
        self.write("src/b.txt", "longer")
        self.write("docs/a.py", "abc")
        self.commit()
        report = self.payload("inventory", "--include", "src/*", "--exclude", "*skip*", "--min-bytes", "3", "--max-bytes", "4", "--kind", "file")
        self.assertEqual(report["total_entries"], 1)
        self.assertEqual(report["unfiltered_entries"], 4)
        self.assertEqual(report["known_bytes"], 3)
        self.assertEqual(report["groups"][0]["group"], ".py")
        self.assertEqual(report["filters"]["kind"], "file")
        self.assertEqual(self.cli("inventory", "--min-bytes", "4", "--max-bytes", "3").returncode, 1)

    def test_inventory_largest_known_object_distinguishes_zero_from_unknown(self):
        self.write("a.py", "abc")
        self.write("b.py", "abcdef")
        self.write("empty.txt", "")
        self.commit()
        oid = self.git("rev-parse", "HEAD")
        self.git("update-index", "--add", "--cacheinfo", f"160000,{oid},module")
        self.git("commit", "-m", "gitlink")
        report = self.payload("inventory")
        groups = {r["group"]: r for r in report["groups"]}
        self.assertEqual(groups[".py"]["largest_known_bytes"], 6)
        self.assertEqual(groups[".txt"]["largest_known_bytes"], 0)
        self.assertIsNone(groups["(none)"]["largest_known_bytes"])
        self.assertIn("Largest known bytes", self.cli("inventory", "--markdown").stdout)
