import tempfile
import unittest
from pathlib import Path
from unittest import mock

from francken_tv.maptiles import TileCache


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


if __name__ == "__main__":
	unittest.main()
