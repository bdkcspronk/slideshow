"""Jeff de Hosson's commandment of the week."""

import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from francken_tv.providers.commandments import CommandmentsProvider, load_commandments


class CommandmentsTest(unittest.TestCase):
	def setUp(self):
		self.folder = TemporaryDirectory()
		self.path = Path(self.folder.name) / "commandments.txt"
		self.path.write_text("# comment\nOne\n\nTwo\nThree\n", encoding="utf-8")
		self.provider = CommandmentsProvider({"file": str(self.path)}, 8)

	def tearDown(self):
		self.folder.cleanup()

	def shown(self, now):
		return self.provider.slides(now)[0].data["commandment"]

	def test_comments_and_empty_lines_are_skipped(self):
		self.assertEqual(load_commandments(self.path), ["One", "Two", "Three"])

	def test_same_all_week_next_one_on_monday_in_order(self):
		monday = datetime(2026, 10, 19)
		this_week = {self.shown(monday + timedelta(hours=hours)) for hours in range(0, 7 * 24, 5)}
		self.assertEqual(len(this_week), 1)
		weeks = [self.shown(monday + timedelta(weeks=week)) for week in range(6)]
		start = ["One", "Two", "Three"].index(weeks[0])
		self.assertEqual(weeks, [["One", "Two", "Three"][(start + i) % 3] for i in range(6)])   # every one in turn, then again

	def test_the_real_file_has_ten(self):
		self.assertEqual(len(load_commandments(Path(__file__).parent.parent / "config" / "commandments.txt")), 10)

	def test_no_file_no_slide(self):
		self.assertEqual(CommandmentsProvider({"file": "/nonexistent.txt"}, 8).slides(datetime(2026, 10, 19)), [])


if __name__ == "__main__":
	unittest.main()
