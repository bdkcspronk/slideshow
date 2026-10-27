import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from PIL import Image

from francken_tv import server
from francken_tv.settings import Settings

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



class GoingBackTest(unittest.TestCase):
	def test_a_recent_slide_is_drawn_again_and_becomes_current(self):
		from datetime import datetime
		from francken_tv.slides import Slide
		volume = {"now": 40}
		music = Slide("empty.html", 10, update=lambda now: {"volume": volume["now"]}, refresh_seconds=1)
		poster = Slide("empty.html", 10)
		slides = iter([music, poster])
		app = SimpleNamespace(clock=SimpleNamespace(now=datetime.now), announcer=None, settings=Settings(),
			scheduler=SimpleNamespace(next_slide=lambda now: next(slides)))
		renderer = server.SlideRenderer(app)
		first, second = renderer.next_slide(), renderer.next_slide()
		self.assertEqual((first["id"], second["id"], renderer.current), (1, 2, poster))
		again = renderer.again(1)   # the left arrow, back to the music slide
		self.assertEqual((again["id"], again["refresh"], renderer.current), (1, 1, music))
		self.assertIsNone(renderer.again(99))


class ShortcutTest(unittest.TestCase):
	def test_a_shortcut_key_shows_that_slide_type_now(self):
		from datetime import datetime
		from francken_tv.slides import Provider, Slide
		puzzles = Slide("empty.html", 20)

		class Puzzles(Provider):
			def slides(self, now):
				return [puzzles]

		class Chart(Provider):
			def slides(self, now):
				return []   # nobody seen yet today

		app = SimpleNamespace(clock=SimpleNamespace(now=datetime.now), announcer=None, settings=Settings(permanent_pause=True),
			providers={"puzzles": Puzzles(), "presence": Chart()}, shortcuts={"1": "puzzles", "3": "presence"})
		renderer = server.SlideRenderer(app)
		shown = renderer.shortcut("1")
		self.assertEqual((shown["id"], shown["seconds"], renderer.current), (1, 20, puzzles))
		self.assertTrue(shown["permanent_pause"])   # the player learns how long a pause lasts with every slide
		self.assertEqual(renderer.again(1)["id"], 1)   # it's in the history, like any other slide
		self.assertIn("message", renderer.shortcut("3"))
		self.assertIsNone(renderer.shortcut("7"))


if __name__ == "__main__":
	unittest.main()
