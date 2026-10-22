import json
import time
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from urllib.parse import parse_qs, urlparse

from francken_tv.providers.spotify import SpotifyProvider, heard_volume, parse_embed_songs, parse_next, parse_playing, parse_playlist_songs, parse_playlists

NOW = datetime(2026, 10, 14, 15, 0)
TRACK = {
	"is_playing": True, "progress_ms": 61_000, "device": {"volume_percent": 40, "supports_volume": True},
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
				mock.patch("francken_tv.providers.spotify.requests.request", side_effect=[FakeResponse(200, TRACK), FakeResponse(204)]):
			self.provider.refresh(NOW)
		[slide] = self.provider.slides(NOW)
		self.assertEqual((slide.data["title"], slide.data["elapsed"], slide.data["total"]), ("Live Is Life", "1:01", "4:10"))
		self.assertEqual(slide.data["percent"], 24.4)
		self.assertEqual(slide.refresh_seconds, 1)

	def test_no_slide_before_anything_is_known_to_have_played(self):
		self.path.write_text(json.dumps({"client_id": "id", "client_secret": "secret", "refresh_token": "r"}))
		token = FakeResponse(200, {"access_token": "a", "expires_in": 3600})
		with mock.patch("francken_tv.providers.spotify.requests.post", return_value=token), \
				mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(204)):
			self.provider.refresh(NOW)
		self.assertEqual(self.provider.slides(NOW), [])
		self.assertIsNone(self.provider.shortcut_slide(NOW))

	def test_next_song_and_playlists(self):
		self.assertEqual(parse_next({"queue": [TRACK["item"], EPISODE["item"]]}),
			{"title": "Live Is Life", "artist": "Opus", "cover": "https://i.scdn.co/big.jpg", "uri": ""})
		self.assertIsNone(parse_next({"queue": []}))
		playlists = parse_playlists({"items": [{"name": "Borrel", "uri": "spotify:playlist:1", "images": None,
			"owner": {"id": "francken", "display_name": "Francken"}}, None]})
		self.assertEqual(playlists, [{"name": "Borrel", "uri": "spotify:playlist:1", "cover": None, "owner": "Francken", "owner_id": "francken"}])

	def connect(self):
		self.path.write_text(json.dumps({"client_id": "id", "client_secret": "secret", "refresh_token": "r"}))
		token = FakeResponse(200, {"access_token": "a", "expires_in": 3600})
		queue = FakeResponse(200, {"queue": [EPISODE["item"]]})
		with mock.patch("francken_tv.providers.spotify.requests.post", return_value=token), \
				mock.patch("francken_tv.providers.spotify.requests.request", side_effect=[FakeResponse(200, TRACK), queue]):
			self.provider.refresh(NOW)

	def test_slide_shows_the_next_song(self):
		self.connect()
		[slide] = self.provider.slides(NOW)
		self.assertEqual(slide.data["next"]["title"], "Episode 1")
		self.assertEqual((slide.data["elapsed_seconds"], slide.data["total_seconds"]), (61, 250))
		self.assertEqual(slide.data["volume"], 40)

	def test_a_queued_song_redraws_the_slide_right_away(self):
		self.connect()
		before = self.provider.slides(NOW)[0].data["state"]
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(204)):
			self.provider.action("queue", ["spotify:track:queued"], NOW)
		queued = TRACK["item"] | {"id": "queued", "name": "Queued Song", "uri": "spotify:track:queued"}
		with mock.patch("francken_tv.providers.spotify.requests.request",
				side_effect=[FakeResponse(200, TRACK), FakeResponse(200, {"queue": [queued]})]):
			self.provider.refresh(NOW)   # the same song still plays...
		[slide] = self.provider.slides(NOW)
		self.assertEqual(slide.data["next"]["title"], "Queued Song")
		self.assertNotEqual(slide.data["state"], before)   # ...but the slide redraws to show the new next song

	def test_play_a_playlist(self):
		self.connect()
		self.provider.playlists = [{"name": "Borrel", "uri": "spotify:playlist:1", "cover": None}]
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(404)):
			slide, message = self.provider.action("play", ["spotify:playlist:1"], NOW)
		self.assertIsNone(slide)
		self.assertIn("No Spotify player is active", message)
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(204)) as request, \
				mock.patch("francken_tv.providers.spotify.time.sleep"):
			slide, message = self.provider.action("play", ["spotify:playlist:1"], NOW)
		self.assertEqual(request.call_args_list[0].kwargs["json"], {"context_uri": "spotify:playlist:1"})
		self.assertEqual((slide.template, message), ("spotify.html", "Playing Borrel"))

	def test_skip_and_volume(self):
		self.connect()
		self.provider.playing.volume = 95
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(204)) as request:
			slide, message = self.provider.action("volume_up", [], NOW)
		self.assertEqual(request.call_args.args[:2], ("PUT", "https://api.spotify.com/v1/me/player/volume?volume_percent=100"))
		self.assertEqual((slide, message, self.provider.playing.volume), (None, None, 100))
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(204)) as request, \
				mock.patch.object(self.provider, "catch_up"):
			slide, message = self.provider.action("skip", [], NOW)
		self.assertEqual(request.call_args_list[0].args[:2], ("POST", "https://api.spotify.com/v1/me/player/next"))
		self.assertEqual(slide.template, "spotify.html")   # the old song, until Spotify reports the new one
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(403)):
			slide, message = self.provider.action("toggle", [], NOW)
		self.assertIn("Premium", message)

	def test_playlist_songs_old_and_new_format(self):
		songs = parse_playlist_songs({"items": [{"item": TRACK["item"] | {"uri": "spotify:track:abc"}}, {"track": EPISODE["item"] | {"uri": "spotify:episode:1"}}, {"item": None}]})
		self.assertEqual([(s["title"], s["artist"], s["length"]) for s in songs], [("Live Is Life", "Opus", "4:10"), ("Episode 1", "A Podcast", "30:00")])

	def test_search_play_and_queue(self):
		self.connect()
		result = {"tracks": {"items": [TRACK["item"] | {"uri": "spotify:track:abc"}]}}
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(200, result)):
			slide, _ = self.provider.action("search", ["live is life"], NOW)
		self.assertEqual((slide.template, slide.data["songs"][0]["uri"]), ("spotify_search.html", "spotify:track:abc"))
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(204)) as request, \
				mock.patch("francken_tv.providers.spotify.time.sleep"):
			self.provider.action("play_song", ["spotify:track:abc|spotify:playlist:1"], NOW)
			self.assertEqual(request.call_args_list[0].kwargs["json"], {"context_uri": "spotify:playlist:1", "offset": {"uri": "spotify:track:abc"}})
			slide, message = self.provider.action("queue", ["spotify:track:abc"], NOW)
			self.assertEqual(request.call_args.kwargs["params"], {"uri": "spotify:track:abc"})
		self.assertEqual(message, f"Added {slide.data['songs'][0]['title']} to the queue")
		self.assertEqual((slide.template, slide.data["message"], slide.data["queued"]), ("spotify_search.html", message, {"spotify:track:abc"}))   # the popup and the tick

	def test_playlists_without_permission_ask_for_a_new_login(self):
		self.connect()
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(403)):
			slide, message = self.provider.action("playlists", [], NOW)
		self.assertIsNone(slide)
		self.assertIn("/spotify/login", message)

	def test_old_login_asks_to_allow_the_buttons(self):
		self.path.write_text(json.dumps({"client_id": "id", "client_secret": "secret", "refresh_token": "r"}))
		token = FakeResponse(200, {"access_token": "a", "expires_in": 3600, "scope": "user-read-playback-state user-read-currently-playing"})
		with mock.patch("francken_tv.providers.spotify.requests.post", return_value=token), \
				mock.patch("francken_tv.providers.spotify.requests.request", side_effect=[FakeResponse(200, TRACK), FakeResponse(204)]):
			self.provider.refresh(NOW)
		with mock.patch("francken_tv.providers.spotify.requests.request") as request:
			slide, message = self.provider.action("skip", [], NOW)
		request.assert_not_called()   # no use asking Spotify
		self.assertIn("/spotify/login", message)

	def test_play_on_the_tv_speaker_when_no_player_is_active(self):
		self.connect()
		devices = FakeResponse(200, {"devices": [{"id": "phone", "name": "Phone"}, {"id": "tv", "name": "Francken TV"}]})
		with mock.patch("francken_tv.providers.spotify.requests.request", side_effect=[FakeResponse(404), devices, FakeResponse(204)]) as request, \
				mock.patch.object(self.provider, "catch_up"):
			slide, message = self.provider.action("play_song", ["spotify:track:abc"], NOW)
		retry = request.call_args_list[2]
		self.assertEqual((retry.args[1], retry.kwargs["params"], retry.kwargs["json"]), ("https://api.spotify.com/v1/me/player/play", {"device_id": "tv"}, {"uris": ["spotify:track:abc"]}))
		with mock.patch("francken_tv.providers.spotify.requests.request", side_effect=[FakeResponse(404), FakeResponse(200, {"devices": []})]):
			slide, message = self.provider.action("play_song", ["spotify:track:abc"], NOW)
		self.assertIn("Francken TV speaker isn't running", message)

	def test_songs_of_someone_elses_playlist_come_from_the_widget(self):
		self.connect()
		html = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"pageProps": {"state": {"data": {"entity": {
			"trackList": [{"uri": f"spotify:track:{i}", "title": f"Song {i}", "subtitle": "Band", "duration": 61_000} for i in range(20)]}}}}}}) + "</script>"
		self.assertEqual(parse_embed_songs("<html>changed</html>"), [])
		widget = FakeResponse(200)
		widget.text = html
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(403)), \
				mock.patch("francken_tv.providers.spotify.requests.get", return_value=widget):
			slide, _ = self.provider.action("songs", ["spotify:playlist:p1|1"], NOW)
		self.assertEqual((len(slide.data["songs"]), slide.data["songs"][0]["title"], slide.data["pages"]), (4, "Song 16", 2))

	def test_playlists_in_pages(self):
		self.connect()
		page = {"items": [{"name": f"List {i}", "uri": f"spotify:playlist:{i}", "images": []} for i in range(12)], "total": 30}
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(200, page)) as request:
			slide, _ = self.provider.action("playlists", ["2"], NOW)
		self.assertEqual(request.call_args.kwargs["params"], {"limit": 12, "offset": 24})
		self.assertEqual((slide.data["page"], slide.data["pages"]), (2, 3))

	def test_catch_up_stops_as_soon_as_spotify_reports_the_change(self):
		self.connect()
		paused = TRACK | {"is_playing": False}
		answers = [FakeResponse(200, TRACK), FakeResponse(200, paused), FakeResponse(200, paused)]
		with mock.patch("francken_tv.providers.spotify.requests.request", side_effect=answers) as request, \
				mock.patch("francken_tv.providers.spotify.time.sleep"):
			self.provider.catch_up(NOW)
		self.assertEqual(request.call_count, 2)   # still playing, then paused: done
		self.assertFalse(self.provider.playing.is_playing)

	def test_volume_on_our_speaker_goes_by_how_it_sounds(self):
		self.connect()
		self.provider.playing.device, self.provider.playing.volume = "Francken TV", 83   # sounds like 50%
		self.assertEqual(self.provider.view()["volume"], heard_volume(83))
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(204)) as request:
			self.provider.action("volume_up", [], NOW)
		self.assertEqual(request.call_args.args[1], "https://api.spotify.com/v1/me/player/volume?volume_percent=88")   # 60% heard
		self.assertAlmostEqual(self.provider.view()["volume"], 60, delta=1)

	def test_search_finds_albums_and_opens_their_songs(self):
		self.connect()
		album = {"name": "ABBA Gold", "uri": "spotify:album:gold", "artists": [{"name": "ABBA"}], "release_date": "2008-11-10",
			"images": [{"url": "big", "width": 640}, {"url": "mid", "width": 300}, {"url": "small", "width": 64}]}
		found = {"tracks": {"items": [TRACK["item"] | {"uri": "spotify:track:abc"}]}, "albums": {"items": [album]}}
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(200, found)):
			slide, _ = self.provider.action("search", ["abba"], NOW)
		self.assertEqual(slide.data["cards"], [{"name": "ABBA Gold", "subtitle": "2008 \u00b7 ABBA", "uri": "spotify:album:gold", "cover": "mid", "kind": "Album"}])
		songs = {"items": [TRACK["item"] | {"uri": "spotify:track:abc"}], "total": 19}
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(200, songs)) as request:
			slide, _ = self.provider.action("songs", ["spotify:album:gold"], NOW)
		self.assertEqual(request.call_args.args[1], "https://api.spotify.com/v1/albums/gold/tracks")
		self.assertEqual((slide.data["playlist"]["name"], slide.data["pages"], slide.data["back"]),
			("ABBA Gold", 2, {"action": "search", "value": "abba", "label": "Search"}))

	def test_search_for_playlists_with_the_chips(self):
		self.connect()
		playlist = {"name": "Borrel Hits", "uri": "spotify:playlist:borrel", "owner": {"display_name": "Francken"}, "images": []}
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(200, {})):
			self.provider.action("search", ["borrel"], NOW)
		found = {"playlists": {"items": [None, playlist]}}   # Spotify leaves gaps in the list
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(200, found)) as request:
			slide, _ = self.provider.action("search_kind", ["playlists"], NOW)   # the last search, just playlists
		self.assertEqual(request.call_args.kwargs["params"], {"q": "borrel", "type": "playlist", "limit": 10})
		self.assertEqual((slide.data["kind"], slide.data["cards"]), ("playlists", [{"name": "Borrel Hits", "subtitle": "By Francken",
			"uri": "spotify:playlist:borrel", "cover": None, "kind": "Playlist"}]))
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(200, found)) as request:
			slide, _ = self.provider.action("search", ["party"], NOW)   # a new search keeps the chip
		self.assertEqual(request.call_args.kwargs["params"]["type"], "playlist")
		songs = {"items": [TRACK["item"] | {"uri": "spotify:track:abc"}], "total": 1}
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(200, songs)):
			slide, _ = self.provider.action("songs", ["spotify:playlist:borrel"], NOW)
		self.assertEqual((slide.data["playlist"]["name"], slide.data["back"]), ("Borrel Hits", {"action": "search", "value": "party", "label": "Search"}))

	def test_all_shows_albums_and_playlists(self):
		self.connect()
		albums = [{"name": f"Album {i}", "uri": f"spotify:album:{i}"} for i in range(5)]
		playlists = [{"name": f"List {i}", "uri": f"spotify:playlist:{i}"} for i in range(5)]
		found = {"albums": {"items": albums}, "playlists": {"items": playlists[:1]}}
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(200, found)):
			slide, _ = self.provider.action("search", ["x"], NOW)
		self.assertEqual([card["name"] for card in slide.data["cards"]], ["Album 0", "Album 1", "Album 2", "List 0"])   # few playlists: more albums
		found["playlists"]["items"] = playlists
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(200, found)):
			slide, _ = self.provider.action("search", ["x"], NOW)
		self.assertEqual([card["name"] for card in slide.data["cards"]], ["Album 0", "Album 1", "List 0", "List 1"])

	def test_music_starts_on_our_speaker_when_the_slideshow_starts(self):
		self.path.write_text(json.dumps({"client_id": "id", "client_secret": "secret", "refresh_token": "r"}))
		provider = SpotifyProvider({"start_playlist": "spotify:playlist:borrel"}, self.path, 8)
		token = FakeResponse(200, {"access_token": "a", "expires_in": 3600})
		nothing, no_speaker = FakeResponse(204), FakeResponse(200, {"devices": []})
		speaker = FakeResponse(200, {"devices": [{"id": "tv", "name": "Francken TV"}]})
		with mock.patch("francken_tv.providers.spotify.requests.post", return_value=token), \
				mock.patch("francken_tv.providers.spotify.requests.request",
					side_effect=[nothing, no_speaker, nothing, speaker, FakeResponse(204), nothing, speaker, FakeResponse(204), nothing, nothing]) as request:
			provider.refresh(NOW)   # the speaker isn't there yet (spotifyd starts later)
			provider.refresh(NOW)   # now it is: resume the last session there
			provider.refresh(NOW)   # still nothing playing: the start playlist
			provider.refresh(NOW)   # done: only what's playing, and (nothing) what played last
		calls = [(c.args[0], c.args[1].rsplit("/v1", 1)[-1], c.kwargs.get("json")) for c in request.call_args_list]
		self.assertEqual(calls[4], ("PUT", "/me/player", {"device_ids": ["tv"], "play": True}))
		self.assertEqual(calls[7], ("PUT", "/me/player/play", {"context_uri": "spotify:playlist:borrel"}))
		self.assertEqual(calls[9][1], "/me/player/recently-played")
		self.assertEqual(len(calls), 10)
		self.assertIsNone(provider.start_step)

	def test_music_playing_elsewhere_is_left_alone_on_start(self):
		self.connect()   # TRACK is playing
		self.assertIsNone(self.provider.start_step)

	def test_paused_on_our_speaker_just_plays_on_start(self):
		self.path.write_text(json.dumps({"client_id": "id", "client_secret": "secret", "refresh_token": "r"}))
		provider = SpotifyProvider({}, self.path, 8)
		token = FakeResponse(200, {"access_token": "a", "expires_in": 3600})
		paused_here = FakeResponse(200, TRACK | {"is_playing": False, "device": {"name": "Francken TV", "volume_percent": 80}})
		speaker = FakeResponse(200, {"devices": [{"id": "tv", "name": "Francken TV"}]})
		with mock.patch("francken_tv.providers.spotify.requests.post", return_value=token), \
				mock.patch("francken_tv.providers.spotify.requests.request",
					side_effect=[paused_here, FakeResponse(200, {"queue": []}), speaker, FakeResponse(204)]) as request:
			provider.refresh(NOW)
		play = request.call_args_list[3]
		self.assertEqual((play.args[0], play.args[1], play.kwargs["params"]), ("PUT", "https://api.spotify.com/v1/me/player/play", {"device_id": "tv"}))

	def test_restarting_the_song_redraws_the_slide(self):
		self.connect()   # TRACK at 1:01
		state = self.provider.view()["state"]
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(200, TRACK | {"progress_ms": 0})):
			self.provider.refresh(NOW)   # the ⏮ button restarted it
		self.assertNotEqual(self.provider.view()["state"], state)
		self.assertEqual(self.provider.view()["elapsed"], "0:00")

	def idle_provider(self):
		self.path.write_text(json.dumps({"client_id": "id", "client_secret": "secret", "refresh_token": "r"}))
		self.provider = SpotifyProvider({"play_on_start": False}, self.path, 8)
		self.provider.access_token, self.provider.token_expires = "a", time.monotonic() + 3600
		return self.provider

	def test_nothing_playing_shows_the_last_song_paused(self):
		provider = self.idle_provider()
		recent = {"items": [{"track": TRACK["item"] | {"uri": "spotify:track:abc"}, "context": {"uri": "spotify:playlist:borrel"}}]}
		with mock.patch("francken_tv.providers.spotify.requests.request",
				side_effect=[FakeResponse(204), FakeResponse(200, recent), FakeResponse(200, {"name": "Borrel Hits"}), FakeResponse(204)]) as request:
			provider.refresh(NOW)
			provider.refresh(NOW)   # known now: not asked again
		self.assertEqual(request.call_count, 4)
		[slide] = provider.slides(NOW)
		data = slide.data
		self.assertEqual((slide.template, data["title"], data["is_playing"], data["elapsed"]), ("spotify.html", "Live Is Life", False, "0:00"))
		self.assertEqual((data["device"], data["on_speaker"], data["volume"]), ("Borrel Hits", True, None))   # no "Play on TV"
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(204)) as request, \
				mock.patch.object(provider, "catch_up"):
			provider.action("toggle", [], NOW)   # ▶: on with the playlist from that song
		self.assertEqual(request.call_args.kwargs["json"],
			{"context_uri": "spotify:playlist:borrel", "offset": {"uri": "spotify:track:abc"}, "position_ms": 0})

	def test_what_played_while_watching_continues_where_it_stopped(self):
		provider = self.idle_provider()
		with mock.patch("francken_tv.providers.spotify.requests.request",
				side_effect=[FakeResponse(200, TRACK | {"context": {"uri": "spotify:artist:opus"}}), FakeResponse(200, {"queue": []}), FakeResponse(204),
					FakeResponse(200, {"name": "Opus"})]) as request:
			provider.refresh(NOW)
			provider.refresh(NOW)   # stopped: no need to ask what played last, only the artist's name
		self.assertEqual(request.call_args.args[1], "https://api.spotify.com/v1/artists/opus")
		data = provider.slides(NOW)[0].data
		self.assertEqual((data["title"], data["elapsed"], data["is_playing"], data["device"]), ("Live Is Life", "1:01", False, "Opus"))
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(204)) as request, \
				mock.patch.object(provider, "catch_up"):
			provider.action("skip", [], NOW)   # an artist can't start at a song: that song, then the next
		play, skip = request.call_args_list
		self.assertEqual(play.kwargs["json"]["uris"], [""])   # (TRACK has no uri)
		self.assertAlmostEqual(play.kwargs["json"]["position_ms"], 61_000, delta=100)
		self.assertEqual(skip.args[1], "https://api.spotify.com/v1/me/player/next")

	def test_an_old_login_shows_nothing_until_something_plays(self):
		provider = self.idle_provider()
		with mock.patch("francken_tv.providers.spotify.requests.request", side_effect=[FakeResponse(204), FakeResponse(403)]):
			provider.refresh(NOW)   # logged in before recently played was asked
		self.assertEqual(provider.slides(NOW), [])

	def test_search_people_and_open_their_playlists(self):
		self.connect()
		library = {"items": [{"name": "Borrel", "uri": "spotify:playlist:1", "owner": {"id": "jan123", "display_name": "Jan de Vries"}},
			{"name": "Feest", "uri": "spotify:playlist:3", "owner": {"id": "jan123", "display_name": "Jan de Vries"}},
			{"name": "Mine", "uri": "spotify:playlist:2", "owner": {"id": "francken", "display_name": "Francken"}}], "total": 3}
		with mock.patch("francken_tv.providers.spotify.requests.request", side_effect=[FakeResponse(200, {}), FakeResponse(200, library)]):
			slide, _ = self.provider.action("search", ["JAN"], NOW)   # the keyboard types capitals
		self.assertEqual(slide.data["cards"], [{"name": "Jan de Vries", "subtitle": "2 playlists", "uri": "spotify:user:jan123",
			"cover": None, "kind": "Profile", "person": True}])
		with mock.patch("francken_tv.providers.spotify.requests.request") as request:
			slide, _ = self.provider.action("search_kind", ["people"], NOW)
			self.assertEqual([card["name"] for card in slide.data["cards"]], ["Jan de Vries"])
			slide, _ = self.provider.action("person", ["spotify:user:jan123"], NOW)
		request.assert_not_called()   # the library is remembered
		self.assertEqual((slide.template, [p["name"] for p in slide.data["playlists"]]), ("spotify_playlists.html", ["Borrel", "Feest"]))
		with mock.patch("francken_tv.providers.spotify.requests.request", return_value=FakeResponse(200, {"items": [], "total": 0})):
			slide, _ = self.provider.action("songs", ["spotify:playlist:1"], NOW)
		self.assertEqual(slide.data["back"], {"action": "person", "value": "spotify:user:jan123", "label": "Jan de Vries"})

if __name__ == "__main__":
	unittest.main()
