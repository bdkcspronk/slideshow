"""The latest xkcd."""

import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from francken_tv.config import DATA_DIR
from francken_tv.providers.xkcd import XkcdProvider

LATEST = {"num": 3314, "title": "Vulnerability", "safe_title": "Vulnerability", "img": "https://imgs.xkcd.com/comics/vulnerability.png",
	"alt": "Other numbers are largely unaffected.", "year": "2026", "month": "10", "day": "21"}


def fake_get(json=None, missing=()):
	def get(url, timeout):
		if url.endswith(".json"):
			return mock.Mock(ok=True, json=lambda: json, raise_for_status=lambda: None)
		ok = url not in missing
		return mock.Mock(ok=ok, content=url.encode() if ok else b"", raise_for_status=lambda: None)
	return get


class XkcdTest(unittest.TestCase):
	def setUp(self):
		DATA_DIR.mkdir(exist_ok=True)
		self.folder = TemporaryDirectory(dir=DATA_DIR)   # served as /files/, like data/cache/xkcd
		self.provider = XkcdProvider({}, Path(self.folder.name), 15)

	def tearDown(self):
		self.folder.cleanup()

	def test_the_latest_comic_in_double_size(self):
		with mock.patch("francken_tv.providers.xkcd.requests.get", side_effect=fake_get(LATEST)):
			self.provider.refresh(datetime(2026, 10, 22, 12))
		[slide] = self.provider.slides(datetime(2026, 10, 22, 12))
		comic = slide.data["comic"]
		self.assertEqual((comic.number, comic.title, comic.alt), (3314, "Vulnerability", "Other numbers are largely unaffected."))
		self.assertEqual((Path(self.folder.name) / "3314.png").read_bytes(), b"https://imgs.xkcd.com/comics/vulnerability_2x.png")

	def test_normal_size_without_a_double_one_and_old_comics_are_deleted(self):
		with mock.patch("francken_tv.providers.xkcd.requests.get", side_effect=fake_get(LATEST)):
			self.provider.refresh(datetime(2026, 10, 22, 12))
		newer = LATEST | {"num": 3315, "img": "https://imgs.xkcd.com/comics/next.png"}
		with mock.patch("francken_tv.providers.xkcd.requests.get", side_effect=fake_get(newer, missing={"https://imgs.xkcd.com/comics/next_2x.png"})):
			self.provider.refresh(datetime(2026, 10, 24, 12))
		self.assertEqual([p.name for p in Path(self.folder.name).iterdir()], ["3315.png"])
		self.assertEqual((Path(self.folder.name) / "3315.png").read_bytes(), b"https://imgs.xkcd.com/comics/next.png")

	def test_at_most_once_every_half_hour(self):
		with mock.patch("francken_tv.providers.xkcd.requests.get", side_effect=fake_get(LATEST)):
			self.provider.refresh(datetime(2026, 10, 22, 12))
		shown = lambda minute: len(self.provider.slides(datetime(2026, 10, 22, 12, minute)))
		self.assertEqual([shown(m) for m in (0, 10, 29, 30, 45, 59)], [1, 0, 0, 1, 0, 0])
		self.assertIsNotNone(self.provider.shortcut_slide(datetime(2026, 10, 22, 12, 40)))   # the shortcut key: any time

	def test_no_slide_before_the_first_download(self):
		self.assertEqual(self.provider.slides(datetime(2026, 10, 22)), [])


if __name__ == "__main__":
	unittest.main()
