"""The emergency response officers slide: one officer per picture, named after the file."""

import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from francken_tv.config import DATA_DIR
from francken_tv.providers.ero import EroProvider, school_year

NOW = datetime(2026, 10, 22, 12, 0)


class EroTest(unittest.TestCase):
	def setUp(self):
		DATA_DIR.mkdir(exist_ok=True)
		self.folder = TemporaryDirectory(dir=DATA_DIR)
		self.addCleanup(self.folder.cleanup)
		self.path = Path(self.folder.name)

	def test_officers_named_after_their_pictures(self):
		for name in ("sam_de_vries.png", "Alex.PNG", "notes.txt"):
			(self.path / name).write_bytes(b"x")
		[slide] = EroProvider({"folder": str(self.path)}, 15).slides(NOW)
		self.assertEqual([o["name"] for o in slide.data["officers"]], ["Alex", "sam de vries"])
		self.assertTrue(slide.data["officers"][0]["photo"].startswith("/files/"))

	def test_the_academic_year_starts_in_september(self):
		self.assertEqual(school_year(datetime(2026, 11, 12)), "'26-'27")
		self.assertEqual(school_year(datetime(2027, 8, 31)), "'26-'27")
		self.assertEqual(school_year(datetime(2027, 9, 1)), "'27-'28")

	def test_left_out_without_pictures(self):
		self.assertEqual(EroProvider({"folder": str(self.path)}, 15).slides(NOW), [])
		self.assertEqual(EroProvider({"folder": str(self.path / "missing")}, 15).slides(NOW), [])


if __name__ == "__main__":
	unittest.main()
