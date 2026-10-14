import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from PIL import Image

from francken_tv import server

DAY = 24 * 3600


class FittedPostersTest(unittest.TestCase):
	def setUp(self):
		self.folder = TemporaryDirectory()
		self.dir = Path(self.folder.name)
		self.original_dir = server.FITTED_DIR
		server.FITTED_DIR = self.dir / "fitted"

	def tearDown(self):
		server.FITTED_DIR = self.original_dir
		self.folder.cleanup()

	def test_unused_copies_are_removed_after_a_week(self):
		self.dir.joinpath("fitted").mkdir()
		recent, old = self.dir / "fitted" / "recent.png", self.dir / "fitted" / "old.png"
		recent.write_bytes(b"x")
		old.write_bytes(b"x")
		os.utime(recent, (time.time() - 6 * DAY,) * 2)
		os.utime(old, (time.time() - 8 * DAY,) * 2)
		self.assertEqual(server.clean_fitted(self.dir / "fitted"), 1)
		self.assertEqual([p.name for p in (self.dir / "fitted").iterdir()], ["recent.png"])

	def test_showing_a_poster_keeps_its_copy(self):
		poster = self.dir / "poster.png"
		Image.new("RGB", (4000, 2000), "red").save(poster)
		renderer = server.SlideRenderer(SimpleNamespace(screen_size=(1920, 1080)))
		renderer.last_cleanup = time.time()   # no cleanup during this test
		copy = renderer.fitted_image(poster)
		self.assertEqual(Image.open(copy).size, (1920, 960))
		os.utime(copy, (time.time() - 8 * DAY,) * 2)   # as if not shown for 8 days...
		renderer.fitted_image(poster)                   # ...then shown again
		self.assertEqual(server.clean_fitted(self.dir / "fitted"), 0)
		self.assertTrue(copy.exists())


if __name__ == "__main__":
	unittest.main()
