"""Event photos, quotes and the bieruur song."""

import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from francken_tv.nextcloud import Entry
from francken_tv.providers.bieruur import BieruurSettings, BieruurSong
from francken_tv.providers.event_photos import most_recent_albums, pick_evenly
from francken_tv.providers.quote import clean_quote, contains_blocked_word, read_quotes


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


class PickEvenlyTest(unittest.TestCase):
	def test_as_many_from_each_event(self):
		big, medium, small = [("big", i) for i in range(300)], [("medium", i) for i in range(40)], [("small", i) for i in range(3)]
		picked = pick_evenly([big, medium, small], 15)
		counts = {name: sum(1 for group, _ in picked if group == name) for name in ("big", "medium", "small")}
		self.assertEqual(counts, {"big": 6, "medium": 6, "small": 3})   # the small event has only 3: the others make up the rest
		self.assertEqual(len(set(picked)), 15)
		self.assertEqual(len(pick_evenly([small], 15)), 3)


class QuotesTest(unittest.TestCase):
	def test_read_quotes_skips_empty_rows(self):
		quotes = read_quotes('﻿Quote,name\n"Physics is fun",Alice\n,Bob\n')
		self.assertEqual(quotes, [{"quote": "Physics is fun", "author": "Alice"}])

	def test_quotation_marks_from_the_sheet_are_removed(self):
		# The slide adds its own quotation marks; people sometimes type them into the sheet too.
		self.assertEqual(clean_quote('"Physics is fun"'), "Physics is fun")
		self.assertEqual(clean_quote("“Het is bieruur”"), "Het is bieruur")
		self.assertEqual(clean_quote('He said "hi" to me'), "He said hi to me")
		self.assertEqual(clean_quote("'it's fine'"), "it's fine")   # single quotes only around the whole quote
		self.assertEqual(clean_quote("it's fine"), "it's fine")
		quotes = read_quotes('﻿Quote,name\n"""Physics is fun""",Alice\n"""""",Bob\n')
		self.assertEqual(quotes, [{"quote": "Physics is fun", "author": "Alice"}])   # only marks: skipped

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

	def test_quotes_with_blocked_words_are_never_shown(self):
		from francken_tv.providers.quote import QuoteProvider

		class SilentAnnouncer:
			quotes_enabled = False

			def prepare(self, text):
				pass
		with TemporaryDirectory() as folder:
			blocked = Path(folder) / "filter.txt"
			blocked.write_text("# a comment\nheck\n", encoding="utf-8")
			provider = QuoteProvider({"blocked_words": str(blocked)}, Path("unused.csv"), SilentAnnouncer(), 8)
			provider.quotes = [{"quote": "Oh heck", "author": "x"}, {"quote": "Fine", "author": "y"}]
			self.assertEqual({provider.slides(datetime(2026, 10, 14))[0].data["quote"] for _ in range(10)}, {"Fine"})
			provider.quotes = [{"quote": "Oh heck", "author": "x"}]
			self.assertEqual(provider.slides(datetime(2026, 10, 14)), [])   # nothing left: no quote slide


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


class PhotoOrderTest(unittest.TestCase):
	def test_every_photo_is_shown_before_any_comes_back(self):
		from francken_tv.config import DATA_DIR
		from francken_tv.providers.event_photos import Album, EventPhotosProvider, Photo
		DATA_DIR.mkdir(exist_ok=True)
		with TemporaryDirectory(dir=DATA_DIR) as folder:
			album = Album("a", date(2026, 10, 9), "Bowling")
			provider = EventPhotosProvider({}, Path(folder), 8)
			for i in range(10):
				(Path(folder) / f"{i}.jpg").write_bytes(b"")
			provider.photos = [Photo(Path(folder) / f"{i}.jpg", album) for i in range(10)]
			shown = [provider.slides(datetime(2026, 10, 14))[0].data["urls"][0] for _ in range(20)]
			self.assertEqual(len(set(shown[:10])), 10)   # the first ten rounds: all different
			self.assertEqual(set(shown[10:]), set(shown[:10]))   # then all again, in a new order


class FakeNextcloud:
	"""Two years, one album, and twenty photos; downloads write a small file."""

	def list_folder(self, path):
		if path == "images/albums/":
			return [Entry("images/albums/2026/", True)]
		if path == "images/albums/2026/":
			return [Entry("images/albums/2026/2026-10-12-Dies-Natalis/", True)]
		return [Entry(f"{path}photo{i}.jpg", False) for i in range(20)]

	def download(self, path, destination):
		destination.write_bytes(b"jpg")


class EventPhotoRefreshTest(unittest.TestCase):
	def test_previous_batch_is_kept_for_one_refresh(self):
		from francken_tv.providers.event_photos import EventPhotosProvider
		with TemporaryDirectory() as folder:
			provider = EventPhotosProvider({"photos_per_event": 5}, Path(folder), 8)
			provider.client = FakeNextcloud()
			now = datetime(2026, 10, 14, 12, 0)
			provider.refresh(now)
			first = {photo.path for photo in provider.photos}
			provider.refresh(now)
			self.assertTrue(all(path.exists() for path in first))   # still shown in the current round
			second = {photo.path for photo in provider.photos}
			provider.refresh(now)
			on_disk = set(Path(folder).iterdir())
			self.assertTrue(on_disk <= second | {photo.path for photo in provider.photos})   # older ones are gone


class FakeAnnouncer:
	def __init__(self):
		self.played = []
		self.playing = False

	def play_music(self, path):
		self.played.append(path.name)
		self.playing = True
		return True

	def music_playing(self):
		return self.playing


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

	def test_spotify_is_quieter_while_the_song_plays(self):
		ducks = []
		self.song.duck = ducks.append
		self.song.in_background = ducks.append   # (no thread in the test)
		start = datetime(2026, 10, 14, 15, 59, 21)
		self.song.tick(start - timedelta(minutes=5))   # the song is chosen
		self.song.tick(start)
		self.assertEqual(ducks, [True])   # down once the song started
		self.song.tick(start + timedelta(seconds=60))
		self.assertEqual(ducks, [True])   # still playing
		self.announcer.playing = False
		self.song.tick(start + timedelta(seconds=200))
		self.song.tick(start + timedelta(seconds=201))
		self.assertEqual(ducks, [True, False])   # back up once, when it's over


if __name__ == "__main__":
	unittest.main()
