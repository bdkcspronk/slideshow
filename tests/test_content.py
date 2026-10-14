"""Event photos, quotes and the bieruur song."""

import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from francken_tv.nextcloud import Entry
from francken_tv.providers.bieruur import BieruurSettings, BieruurSong
from francken_tv.providers.event_photos import most_recent_albums
from francken_tv.providers.quote import contains_blocked_word, read_quotes


class AlbumsTest(unittest.TestCase):
	def test_most_recent_albums_by_date_in_name(self):
		entries = [
			Entry("images/albums/2026/2025-12-12-Karaoke-Borrel/", True),
			Entry("images/albums/2026/2026-10-09-Bowling/", True),
			Entry("images/albums/2026/2026-10-12-Dies-Natalis/", True),
			Entry("images/albums/2026/2026-10-20-Not-Yet/", True),
			Entry("images/albums/2025/2025-02-04_AP_Dinner/", True),
			Entry("images/albums/2026/readme.txt", False),
			Entry("images/albums/2026/Unsorted/", True),
		]
		albums = most_recent_albums(entries, date(2026, 10, 14), 3)
		self.assertEqual([a.title for a in albums], ["Dies Natalis", "Bowling", "Karaoke Borrel"])
		self.assertEqual(albums[0].day, date(2026, 10, 12))


class QuotesTest(unittest.TestCase):
	def test_read_quotes_skips_empty_rows(self):
		quotes = read_quotes('﻿Quote,name\n"Physics is fun",Alice\n,Bob\n')
		self.assertEqual(quotes, [{"quote": "Physics is fun", "author": "Alice"}])

	def test_blocked_words_match_whole_words_only(self):
		self.assertTrue(contains_blocked_word("What the Heck", ["heck"]))
		self.assertFalse(contains_blocked_word("Checkmate", ["heck"]))


class QuoteProviderTest(unittest.TestCase):
	def test_never_the_same_quote_twice_in_a_row(self):
		from francken_tv.providers.quote import QuoteProvider

		class SilentAnnouncer:
			quotes_enabled = False

			def prepare(self, text):
				pass
		provider = QuoteProvider({}, Path("unused.csv"), SilentAnnouncer(), 8)
		provider.quotes = [{"quote": "a", "author": "x"}, {"quote": "b", "author": "y"}]
		shown = [provider.slides(datetime(2026, 10, 14))[0].data["quote"] for _ in range(20)]
		self.assertTrue(all(first != second for first, second in zip(shown, shown[1:])))


class PortraitPairTest(unittest.TestCase):
	def test_portrait_photo_is_paired_with_one_from_the_same_event(self):
		from francken_tv.config import DATA_DIR
		from francken_tv.providers.event_photos import Album, EventPhotosProvider, Photo
		DATA_DIR.mkdir(exist_ok=True)
		with TemporaryDirectory(dir=DATA_DIR) as folder:
			paths = [Path(folder) / f"{i}.jpg" for i in range(3)]
			for path in paths:
				path.write_bytes(b"")
			bowling, dies = Album("a", date(2026, 10, 9), "Bowling"), Album("b", date(2026, 10, 12), "Dies")
			provider = EventPhotosProvider({}, Path(folder), 8)
			provider.photos = [Photo(paths[0], bowling, portrait=True), Photo(paths[1], bowling), Photo(paths[2], dies, portrait=True)]
			provider.photos_per_round = 3
			slides = {slide.data["urls"][0].split("?")[0][-5:]: slide.data["urls"] for slide in provider.slides(datetime(2026, 10, 14))}
			self.assertEqual(len(slides["0.jpg"]), 2)   # portrait, paired with the other Bowling photo
			self.assertIn("1.jpg", slides["0.jpg"][1])
			self.assertEqual(len(slides["1.jpg"]), 1)   # landscape: alone
			self.assertEqual(len(slides["2.jpg"]), 1)   # portrait, but no other photo from that event


class FakeAnnouncer:
	def __init__(self):
		self.played = []

	def play_music(self, path):
		self.played.append(path.name)


class BieruurSongTest(unittest.TestCase):
	def setUp(self):
		self.folder = TemporaryDirectory()
		(Path(self.folder.name) / "toby.mp3").write_bytes(b"")
		self.announcer = FakeAnnouncer()
		settings = BieruurSettings(songs_folder=self.folder.name, song_offsets={"toby.mp3": -39})
		self.song = BieruurSong(settings, self.announcer)

	def tearDown(self):
		self.folder.cleanup()

	def test_song_starts_at_its_offset_once(self):
		start = datetime(2026, 10, 14, 15, 59, 0)
		for second in range(120):
			self.song.tick(start + timedelta(seconds=second))
			if second == 20:
				self.assertEqual(self.announcer.played, [])   # 15:59:20, toby starts at 15:59:21
		self.assertEqual(self.announcer.played, ["toby.mp3"])

	def test_no_song_when_started_long_after_bieruur(self):
		self.song.tick(datetime(2026, 10, 14, 17, 0))
		self.assertEqual(self.announcer.played, [])


if __name__ == "__main__":
	unittest.main()
