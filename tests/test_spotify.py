import json
import time
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from urllib.parse import parse_qs, urlparse

from francken_tv.providers.spotify import SpotifyProvider, parse_playing

NOW = datetime(2026, 10, 14, 15, 0)
TRACK = {
	"is_playing": True, "progress_ms": 61_000,
	"item": {"type": "track", "id": "abc", "name": "Live Is Life", "duration_ms": 250_000,
		"artists": [{"name": "Opus"}], "album": {"name": "Up And Down", "images": [
			{"url": "https://i.scdn.co/small.jpg", "width": 64}, {"url": "https://i.scdn.co/big.jpg", "width": 640}]}},
}
EPISODE = {
	"is_playing": True, "progress_ms": 0,
	"item": {"type": "episode", "id": "ep1", "name": "Episode 1", "duration_ms": 1_800_000,
		"show": {"name": "A Podcast"}, "images": [{"url": "https://i.scdn.co/show.jpg", "width": 300}]},
}


class FakeResponse:
	def __init__(self, status, data=None):
		self.status_code, self.data = status, data
		self.content = json.dumps(data).encode() if data is not None else b""

	def json(self):
		return self.data

	def raise_for_status(self):
		if self.status_code >= 400:
			raise RuntimeError(self.status_code)


class SpotifyTest(unittest.TestCase):
	def setUp(self):
		self.folder = TemporaryDirectory()
		self.path = Path(self.folder.name) / "spotify.json"
		self.provider = SpotifyProvider({}, self.path, 8)

	def tearDown(self):
		self.folder.cleanup()

	def test_parse_track_and_episode(self):
		track = parse_playing(TRACK, time.monotonic())
		self.assertEqual((track.title, track.artist, track.cover), ("Live Is Life", "Opus", "https://i.scdn.co/big.jpg"))
		episode = parse_playing(EPISODE, time.monotonic())
		self.assertEqual((episode.artist, episode.album, episode.cover), ("A Podcast", "Podcast", "https://i.scdn.co/show.jpg"))

	def test_not_connected_means_no_slide(self):
		self.provider.refresh(NOW)
		self.assertEqual(self.provider.slides(NOW), [])
		self.assertIsNone(self.provider.login_url())   # no app keys yet

	def test_login_saves_only_a_refresh_token(self):
		self.path.write_text(json.dumps({"client_id": "id", "client_secret": "secret"}))
		url = self.provider.login_url()
		state = parse_qs(urlparse(url).query)["state"][0]
		self.assertIn("redirect_uri=http%3A%2F%2F127.0.0.1%3A8080%2Fspotify%2Fcallback", url)
		token = FakeResponse(200, {"access_token": "a", "refresh_token": "r", "expires_in": 3600})
		with mock.patch("francken_tv.providers.spotify.requests.post", return_value=token):
			self.provider.finish_login("code", state)
		saved = json.loads(self.path.read_text())
		self.assertEqual(saved, {"client_id": "id", "client_secret": "secret", "refresh_token": "r"})
		self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
		with self.assertRaises(ValueError):   # the same login link can't be used twice
			self.provider.finish_login("code", state)

	def test_now_playing_slide_with_progress(self):
		self.path.write_text(json.dumps({"client_id": "id", "client_secret": "secret", "refresh_token": "r"}))
		token = FakeResponse(200, {"access_token": "a", "expires_in": 3600})
		with mock.patch("francken_tv.providers.spotify.requests.post", return_value=token), \
				mock.patch("francken_tv.providers.spotify.requests.get", return_value=FakeResponse(200, TRACK)):
			self.provider.refresh(NOW)
		[slide] = self.provider.slides(NOW)
		self.assertEqual((slide.data["title"], slide.data["elapsed"], slide.data["total"]), ("Live Is Life", "1:01", "4:10"))
		self.assertEqual(slide.data["percent"], 24.4)
		self.assertEqual(slide.refresh_seconds, 1)

	def test_nothing_playing_means_no_slide(self):
		self.path.write_text(json.dumps({"client_id": "id", "client_secret": "secret", "refresh_token": "r"}))
		token = FakeResponse(200, {"access_token": "a", "expires_in": 3600})
		with mock.patch("francken_tv.providers.spotify.requests.post", return_value=token), \
				mock.patch("francken_tv.providers.spotify.requests.get", return_value=FakeResponse(204)):
			self.provider.refresh(NOW)
		self.assertEqual(self.provider.slides(NOW), [])


if __name__ == "__main__":
	unittest.main()
