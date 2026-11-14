import tempfile
import unittest
from pathlib import Path
from unittest import mock

import json

import requests

from francken_tv.maptiles import RETRY_SECONDS, GoogleTiles, TileCache


class FakeResponse:
	def __init__(self, status_code, content_type="image/png"):
		self.status_code, self.content, self.headers = status_code, b"png", {"Content-Type": content_type}


class TileCacheTest(unittest.TestCase):
	def setUp(self):
		self.folder = tempfile.TemporaryDirectory()
		self.addCleanup(self.folder.cleanup)
		self.tiles = TileCache(Path(self.folder.name), "https://tiles.example/{z}/{x}/{y}.png")

	def test_fetched_once_then_kept(self):
		with mock.patch.object(self.tiles.session, "get", return_value=FakeResponse(200)) as get:
			first = self.tiles.get(3, 4, 2)
			again = self.tiles.get(3, 4, 2)
		self.assertEqual(first, again)
		self.assertEqual(first.read_bytes(), b"png")
		get.assert_called_once()
		self.assertEqual(get.call_args.args[0], "https://tiles.example/3/4/2.png")
		self.assertIn("FranckenTV", self.tiles.session.headers["User-Agent"])   # the tile policy asks who we are

	def test_tiles_that_cant_exist(self):
		with mock.patch.object(self.tiles.session, "get") as get:
			self.assertIsNone(self.tiles.get(2, 4, 0))    # x only goes up to 3 at zoom 2
			self.assertIsNone(self.tiles.get(25, 0, 0))   # too far zoomed in
		get.assert_not_called()

	def test_errors_are_not_kept(self):
		with mock.patch.object(self.tiles.session, "get", return_value=FakeResponse(403, "text/html")):
			self.assertIsNone(self.tiles.get(1, 0, 0))
		self.assertEqual(list(Path(self.folder.name).rglob("*.png")), [])


	def test_at_most_four_downloads_at_a_time(self):
		import threading
		import time
		from francken_tv.maptiles import PARALLEL_DOWNLOADS
		busy, most, lock = 0, 0, threading.Lock()

		def slow_get(url, timeout):
			nonlocal busy, most
			with lock:
				busy += 1
				most = max(most, busy)
			time.sleep(0.05)
			with lock:
				busy -= 1
			return FakeResponse(200)

		with mock.patch.object(self.tiles.session, "get", side_effect=slow_get):
			threads = [threading.Thread(target=self.tiles.get, args=(5, x, 3)) for x in range(20)]   # 20 tiles asked at once
			for thread in threads:
				thread.start()
			for thread in threads:
				thread.join()
		self.assertEqual(most, PARALLEL_DOWNLOADS)
		self.assertEqual(len(list(Path(self.folder.name).rglob("*.png"))), 20)   # all fetched
		self.assertEqual(self.tiles.session.get_adapter("https://tile.openstreetmap.org").poolmanager.connection_pool_kw["maxsize"], PARALLEL_DOWNLOADS)



class GoogleResponse:
	def __init__(self, status_code=200, data=None, content=b"png"):
		self.status_code, self.content, self.data = status_code, content, data or {}
		self.headers = {"Content-Type": "image/png", "Cache-Control": "private, max-age=3600"}

	def json(self):
		return self.data

	def raise_for_status(self):
		if self.status_code >= 400:
			raise requests.HTTPError(f"{self.status_code}")


class GoogleTilesTest(unittest.TestCase):
	def setUp(self):
		folder = tempfile.TemporaryDirectory()
		self.addCleanup(folder.cleanup)
		self.usage = Path(folder.name) / "google_tiles.json"
		self.now = 1_794_600_000.0   # November 2026
		self.google = GoogleTiles("KEY", self.usage, monthly_limit=3, clock=lambda: self.now)
		self.post = mock.patch.object(self.google.session, "post",
			return_value=GoogleResponse(data={"session": "S", "expiry": str(self.now + 14 * 86400)})).start()
		self.get = mock.patch.object(self.google.session, "get", side_effect=self.answer).start()
		self.addCleanup(mock.patch.stopall)
		self.tile_status = 200

	def answer(self, url, params, timeout):
		if "viewport" in url:
			return GoogleResponse(data={"copyright": "Map data ©2026 Google"})
		return GoogleResponse(self.tile_status)

	def test_a_tile_in_english(self):
		self.assertEqual(self.google.get(3, 4, 2), (b"png", "image/png", "private, max-age=3600"))
		self.assertEqual(self.post.call_args.kwargs["json"]["language"], "en-US")
		self.assertEqual(self.get.call_args.args[0], "https://tile.googleapis.com/v1/2dtiles/3/4/2")
		self.assertEqual(self.google.attribution, "Map data ©2026 Google")
		self.google.get(3, 4, 3)
		self.assertEqual(self.post.call_count, 1)   # the session is reused

	def test_openstreetmap_once_the_months_tiles_are_used(self):
		for x in range(3):
			self.assertIsNotNone(self.google.get(2, x, 0))
		self.assertFalse(self.google.usable())
		self.assertIsNone(self.google.get(2, 3, 0))
		self.assertIn("used up", self.google.warnings()[0])
		self.assertEqual(json.loads(self.usage.read_text()), {"month": "2026-11", "tiles": 3})
		self.assertFalse(GoogleTiles("KEY", self.usage, monthly_limit=3, clock=lambda: self.now).usable())   # also after a restart
		self.now += 31 * 86400   # December: free tiles again
		self.assertTrue(self.google.usable())

	def test_openstreetmap_for_an_hour_after_an_error(self):
		self.tile_status = 429
		self.assertIsNone(self.google.get(3, 4, 2))
		self.assertFalse(self.google.usable())
		self.assertIn("failed", self.google.warnings()[0])
		self.now += RETRY_SECONDS
		self.tile_status = 200
		self.assertIsNotNone(self.google.get(3, 4, 2))
		self.assertEqual(self.google.warnings(), [])

	def test_no_tile_there_is_not_an_error(self):
		self.tile_status = 404
		self.assertIsNone(self.google.get(19, 0, 0))
		self.assertTrue(self.google.usable())


if __name__ == "__main__":
	unittest.main()
