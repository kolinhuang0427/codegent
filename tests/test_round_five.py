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
