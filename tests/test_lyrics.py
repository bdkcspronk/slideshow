import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import requests

from francken_tv.lyrics import Lyrics, find_lyrics, from_record, parse_lrc, simple_title
from francken_tv.providers.spotify import SpotifyProvider, parse_playing
from tests.test_spotify import NOW, TRACK

SYNCED = "[00:10.81] Them that's got shall have\n[00:15.37] Them that's not shall lose\n[00:20.00] \n[01:02.50] So the Bible says"


class Response:
	def __init__(self, status, data=None):
		self.status_code, self.data = status, data

	def json(self):
		return self.data

	def raise_for_status(self):
		if self.status_code >= 400:
			raise requests.HTTPError(self.status_code)


class LyricsTest(unittest.TestCase):
	def test_synced_lines(self):
		lines = parse_lrc(SYNCED)
		self.assertEqual([(line.time, line.text) for line in lines],
			[(10.81, "Them that's got shall have"), (15.37, "Them that's not shall lose"), (20.0, ""), (62.5, "So the Bible says")])

	def test_plain_and_instrumental(self):
		plain = from_record({"syncedLyrics": None, "plainLyrics": "One\nTwo"})
		self.assertEqual(([line.text for line in plain.lines], plain.synced), (["One", "Two"], False))
		self.assertTrue(from_record({"instrumental": True}).instrumental)
		self.assertTrue(from_record({"syncedLyrics": SYNCED, "plainLyrics": "x"}).synced)

	def test_titles_without_extras(self):
		self.assertEqual(simple_title("God Bless the Child - Take 1"), "God Bless the Child")
		self.assertEqual(simple_title("Hey Jude - Remastered 2015"), "Hey Jude")
		self.assertEqual(simple_title("Shape of You (feat. Someone)"), "Shape of You")
		self.assertEqual(simple_title("(How Much Is) That Doggie in the Window?"), "(How Much Is) That Doggie in the Window?")

	def test_exact_match_then_search_by_length(self):
		with mock.patch("francken_tv.lyrics.requests.get", return_value=Response(200, {"syncedLyrics": SYNCED})) as get:
			self.assertTrue(find_lyrics("Song", "A, B", "Album", 200).synced)
		self.assertEqual(get.call_args.kwargs["params"]["artist_name"], "A")   # the first artist
		results = [{"duration": 260, "syncedLyrics": SYNCED}, {"duration": 201, "plainLyrics": "Close"}, {"duration": 199, "syncedLyrics": SYNCED}]
		with mock.patch("francken_tv.lyrics.requests.get", side_effect=[Response(404), Response(200, results)]) as get:
			lyrics = find_lyrics("Song - Remastered", "A", "Album", 200)
		self.assertEqual(get.call_args.kwargs["params"]["track_name"], "Song")
		self.assertTrue(lyrics.synced)   # synced and close in length beats plain and closer
		with mock.patch("francken_tv.lyrics.requests.get", side_effect=[Response(404), Response(200, [{"duration": 300}])]):
			self.assertIsNone(find_lyrics("Song", "A", "Album", 200))   # another recording


class SpotifyLyricsTest(unittest.TestCase):
	def setUp(self):
		self.folder = TemporaryDirectory()
		self.addCleanup(self.folder.cleanup)
		self.provider = SpotifyProvider({}, Path(self.folder.name) / "spotify.json", 8)
		self.provider.playing = parse_playing(TRACK, time.monotonic())

	def test_lyrics_button_and_staying_in_the_view(self):
		with mock.patch("francken_tv.providers.spotify.find_lyrics", return_value=Lyrics(parse_lrc(SYNCED), synced=True)) as find:
			slide, _ = self.provider.action("lyrics", [], NOW)
			self.assertEqual(slide.template, "spotify_lyrics.html")
			self.assertEqual(len(slide.data["lyrics"].lines), 4)
			self.assertAlmostEqual(slide.data["progress_seconds"], 61, delta=1)
			self.assertTrue(slide.data["state"].startswith("lyrics abc playing"))
			slide.update(NOW)
			find.assert_called_once()   # looked up once per song, not every redraw
			with mock.patch.object(self.provider, "command", return_value=None), mock.patch.object(self.provider, "catch_up"):
				self.assertEqual(self.provider.action("toggle", ["lyrics"], NOW)[0].template, "spotify_lyrics.html")
				self.assertEqual(self.provider.action("toggle", [], NOW)[0].template, "spotify.html")

	def test_lrclib_down_is_tried_again(self):
		with mock.patch("francken_tv.providers.spotify.find_lyrics", side_effect=requests.ConnectionError("down")):
			slide, _ = self.provider.action("lyrics", [], NOW)
		self.assertTrue(slide.data["lyrics_error"])
		with mock.patch("francken_tv.providers.spotify.find_lyrics", return_value=None):
			self.assertFalse(slide.update(NOW)["lyrics_error"])   # not remembered as "no lyrics"


if __name__ == "__main__":
	unittest.main()
