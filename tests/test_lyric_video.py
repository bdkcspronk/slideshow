import json
import time
from datetime import datetime
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from jinja2 import Environment, FileSystemLoader, select_autoescape

from francken_tv.lyrics import Lyrics, parse_lrc
from francken_tv.providers.lyric_video import LyricVideoProvider
from francken_tv.providers.spotify import SpotifyProvider, parse_playing
from tests.test_spotify import NOW, TRACK

TEMPLATES = Environment(loader=FileSystemLoader(Path(__file__).parent.parent / "francken_tv" / "templates"), autoescape=select_autoescape())   # as in server.py

# The song in TRACK is 61 s along: the second line is being sung.
EVENING = datetime(2026, 10, 14, 21, 0)   # after bieruur
SYNCED = "[00:50.00] First <b>line</b>\n[01:00.00] Them that's got\n[01:10.00] \n[01:20.00] So the Bible says"


class LyricVideoTest(unittest.TestCase):
	def setUp(self):
		folder = TemporaryDirectory()
		self.addCleanup(folder.cleanup)
		credentials = Path(folder.name) / "spotify.json"
		credentials.write_text(json.dumps({"refresh_token": "x"}))
		self.spotify = SpotifyProvider({}, credentials, 8)
		self.spotify.playing = parse_playing(TRACK, time.monotonic())
		self.provider = LyricVideoProvider({"seconds": 30}, self.spotify)

	def find(self, lyrics):
		return mock.patch("francken_tv.providers.spotify.find_lyrics", return_value=lyrics)

	def test_in_the_round_once_the_synced_lyrics_are_known(self):
		with self.find(Lyrics(parse_lrc(SYNCED), synced=True)) as find:
			self.assertEqual(self.provider.slides(EVENING), [])   # slides() doesn't look them up itself
			find.assert_not_called()
			self.provider.refresh(NOW)
			[slide] = self.provider.slides(EVENING)
			slide.update(NOW)
			find.assert_called_once()   # once per song
		self.assertEqual(slide.template, "lyric_video.html")
		self.assertEqual(len(slide.data["lines"]), 4)
		self.assertTrue(slide.data["state"].startswith("lyric-video 4 abc playing"))
		html = TEMPLATES.get_template("slides/lyric_video.html").render(**slide.data)
		self.assertIn('data-time="60.0">Them that&#39;s got</li>', html)
		self.assertIn("First &lt;b&gt;line&lt;/b&gt;", html)   # lyrics are text, not HTML
		self.assertIn("data-playing", html)

	def test_left_out_without_synced_lyrics_or_when_paused(self):
		with self.find(Lyrics(parse_lrc(SYNCED), synced=False)):
			self.provider.refresh(NOW)
			self.assertEqual(self.provider.slides(EVENING), [])
			# The shortcut shows it anyway: the title, big.
			slide = self.provider.shortcut_slide(NOW)
			html = TEMPLATES.get_template("slides/lyric_video.html").render(**slide.data)
			self.assertNotIn("data-lyric-video data-start", html)
			self.assertIn("lyric-video-title", html)
		self.spotify.lyrics.clear()
		with self.find(Lyrics(parse_lrc(SYNCED), synced=True)):
			self.provider.refresh(NOW)
			self.spotify.playing.is_playing = False
			self.assertEqual(self.provider.slides(EVENING), [])

	def test_only_after_bieruur(self):
		with self.find(Lyrics(parse_lrc(SYNCED), synced=True)):
			self.provider.refresh(NOW)
		self.assertEqual(self.provider.slides(NOW), [])   # 15:00, before bieruur
		self.assertIsNotNone(self.provider.shortcut_slide(NOW))   # the shortcut works anyway
		self.assertEqual(len(self.provider.slides(datetime(2026, 10, 14, 16, 0))), 1)
		self.assertEqual(len(self.provider.slides(datetime(2026, 10, 15, 2, 0))), 1)   # past midnight
		self.assertEqual(self.provider.slides(datetime(2026, 10, 15, 8, 0)), [])   # morning

	def test_left_out_during_the_outro(self):
		with self.find(Lyrics(parse_lrc("[00:10.00] Early\n[00:20.00] Done"), synced=True)):
			self.provider.refresh(NOW)
		self.assertEqual(self.provider.slides(EVENING), [])   # at 61 s nothing is sung any more


if __name__ == "__main__":
	unittest.main()
