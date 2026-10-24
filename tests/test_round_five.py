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
