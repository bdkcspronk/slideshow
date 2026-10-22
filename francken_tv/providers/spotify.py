"""What's playing on Spotify: title, artist, album cover, progress and the next song
(templates/slides/spotify.html), with buttons for the previous/next song, pause and the volume.
"Playlists" shows the account's playlists (templates/slides/spotify_playlists.html), tapping one
shows its songs (spotify_songs.html); "Search" finds songs, playlists, albums and people by typing,
with All / Songs / Playlists / Albums / People chips like the desktop app (spotify_search.html).
Tapping a person shows their public playlists (spotify_playlists.html).
Tapping a song plays it. "Lyrics" shows the song's lyrics, the line being sung lit up when LRCLIB
has them synced (spotify_lyrics.html, lyrics.py). The buttons need Spotify Premium.

Uses Spotify's Web API. One-time setup (see README, "Spotify"):
1. Create an app at https://developer.spotify.com/dashboard with redirect URI
   http://127.0.0.1:8080/spotify/callback, and put its keys in ~/.config/slideshow/spotify.json:
   {"client_id": "...", "client_secret": "..."}
2. Open http://127.0.0.1:8080/spotify/login on the TV PC and log in with Spotify.
   The slideshow then adds a refresh token to that file; no password is stored.
   (Logged in before changing playlists was possible? Log in again once, to allow it.)
When nothing plays, the slide shows the last played playlist (or album, or song) with a Play button.
"""

from __future__ import annotations

import json
import math
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import requests

from ..lyrics import Lyrics, find_lyrics
from ..slides import Provider, Slide

log = logging.getLogger(__name__)

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
PLAYING_URL = API + "/me/player?additional_types=episode"   # the song, and the device with its volume
QUEUE_URL = API + "/me/player/queue"
PLAYLISTS_URL = API + "/me/playlists"
EMBED_URL = "https://open.spotify.com/embed/playlist/{id}"   # Spotify's public playlist widget
PLAY_URL = API + "/me/player/play"
PLAYER_URL = API + "/me/player"
SHUFFLE_URL = API + "/me/player/shuffle"
DEVICES_URL = API + "/me/player/devices"
PAUSE_URL = API + "/me/player/pause"
NEXT_URL = API + "/me/player/next"
PREVIOUS_URL = API + "/me/player/previous"
VOLUME_URL = API + "/me/player/volume"
VOLUME_STEP = 10             # in heard volume (see heard_volume)
DB_PER_DECADE_HEARD = 0.6    # loudness heard ~ amplitude^0.6
VOLUME_SETTLE_SECONDS = 4
START_WAIT_SECONDS = 180      # on start: how long to wait for our speaker to show up
JUMP_MS = 3000                # a position this far from what we expect: the song was restarted or moved
CATCH_UP_SECONDS = 3          # after skip/pause/play: how long to wait for Spotify to report it
CATCH_UP_EVERY = 0.25
SCOPES = ("user-read-currently-playing user-read-playback-state user-modify-playback-state "
	"playlist-read-private playlist-read-collaborative user-read-recently-played")
NEW_LOGIN_MESSAGE = "Allow the buttons once: open 127.0.0.1:8080/spotify/login on this PC and click Agree"
QUEUE_EVERY_SECONDS = 30      # the next song is also fetched whenever the song changes
PLAYLISTS_EVERY_SECONDS = 600
PLAYLISTS_PER_PAGE = 12       # as many as fit on the screen
SONGS_PER_PAGE = 16
SEARCH_URL = API + "/search"
SEARCH_RESULTS = 10           # Spotify's maximum for apps in development mode
SEARCH_CARDS = 4              # "All": albums and playlists shown above the songs
SEARCH_CARDS_ONLY = 8         # "Albums" or "Playlists": two rows of them
SEARCH_KINDS = {"all": "track,album,playlist", "songs": "track", "playlists": "playlist", "albums": "album", "people": ""}   # the chips
QUEUE_ADD_URL = API + "/me/player/queue"
# Spotify can't search people, nor show anyone's profile or playlists to an app in development mode:
# People looks for the makers of the account's playlists by name.
LIBRARY_MAX = 500             # playlists read to find their makers
RECENTLY_PLAYED_URL = API + "/me/player/recently-played"
LAST_PLAYED_EVERY_SECONDS = 60   # nothing playing: how often to ask what played last


@dataclass
class NowPlaying:
	id: str
	title: str
	artist: str        # artists, or the show for a podcast episode
	album: str
	cover: str | None
	duration_ms: int
	progress_ms: int
	is_playing: bool
	fetched_at: float  # time.monotonic() when progress_ms was measured
	volume: int | None = None   # of the playing device in %, None if it can't be changed
	device: str = ""            # the name of the device that plays
	uri: str = ""
	context: str = ""           # the playlist, album, ... it plays from ("" for a song on its own)

	def progress(self) -> int:
		"""Progress now, counting the time since Spotify was last asked."""
		elapsed = (time.monotonic() - self.fetched_at) * 1000 if self.is_playing else 0
		return int(min(self.duration_ms, self.progress_ms + elapsed))


def parse_playing(data: dict, fetched_at: float) -> NowPlaying | None:
	item = data.get("item")
	if not item:
		return None
	if item.get("type") == "episode":
		artist, album, images = item.get("show", {}).get("name", ""), "Podcast", item.get("images") or item.get("show", {}).get("images", [])
	else:
		artist = ", ".join(a["name"] for a in item.get("artists", []))
		album, images = item.get("album", {}).get("name", ""), item.get("album", {}).get("images", [])
	cover = biggest_image(images)
	return NowPlaying(
		id=item.get("id") or item.get("uri", ""), title=item.get("name", ""), artist=artist, album=album, cover=cover,
		duration_ms=item.get("duration_ms", 0), progress_ms=data.get("progress_ms") or 0,
		is_playing=bool(data.get("is_playing")), fetched_at=fetched_at,
		volume=device.get("volume_percent") if (device := data.get("device") or {}).get("supports_volume", True) else None,
		device=device.get("name", ""), uri=item.get("uri", ""), context=(data.get("context") or {}).get("uri") or "",
	)


def biggest_image(images: list[dict]) -> str | None:
	return max(images, key=lambda image: image.get("width") or 0)["url"] if images else None


def parse_next(data: dict) -> dict | None:
	"""The first song in the queue (from QUEUE_URL), or None."""
	queue = data.get("queue") or []
	if not queue:
		return None
	item = queue[0]
	if item.get("type") == "episode":
		artist, images = item.get("show", {}).get("name", ""), item.get("images") or item.get("show", {}).get("images", [])
	else:
		artist, images = ", ".join(a["name"] for a in item.get("artists", [])), item.get("album", {}).get("images", [])
	return {"title": item.get("name", ""), "artist": artist, "cover": biggest_image(images), "uri": item.get("uri", "")}


def smallest_image(images: list[dict]) -> str | None:
	"""The smallest picture that is still sharp as a thumbnail (lists can show many)."""
	usable = [image for image in images if (image.get("width") or 300) >= 64]
	return min(usable, key=lambda image: image.get("width") or 300)["url"] if usable else None


def parse_song(item: dict | None) -> dict | None:
	"""A track (or podcast episode) for a list: title, artist, thumbnail, uri, length."""
	if not item or not item.get("uri"):
		return None
	if item.get("type") == "episode":
		artist, images = item.get("show", {}).get("name", ""), item.get("images") or []
	else:
		artist, images = ", ".join(a["name"] for a in item.get("artists", [])), item.get("album", {}).get("images", [])
	return {"title": item.get("name", ""), "artist": artist, "cover": smallest_image(images),
		"uri": item["uri"], "length": minutes(item.get("duration_ms") or 0)}


def card_image(images: list[dict]) -> str | None:
	"""The image closest to 300 pixels wide: sharp enough for a card, not too big to load."""
	images = sorted(images, key=lambda image: abs((image.get("width") or 300) - 300))
	return images[0]["url"] if images else None


def parse_album(item: dict | None) -> dict | None:
	if not item or not item.get("uri"):
		return None
	year = (item.get("release_date") or "")[:4]
	artist = ", ".join(a["name"] for a in item.get("artists", []))
	return {"name": item.get("name", ""), "subtitle": " \u00b7 ".join(part for part in (year, artist) if part),
		"uri": item["uri"], "cover": card_image(item.get("images") or []), "kind": "Album"}


def parse_found_playlist(item: dict | None) -> dict | None:
	"""A playlist from the search (Spotify leaves gaps in that list: None)."""
	if not item or not item.get("uri"):
		return None
	owner = (item.get("owner") or {}).get("display_name") or ""
	return {"name": item.get("name", ""), "subtitle": f"By {owner}" if owner else "", "uri": item["uri"],
		"cover": card_image(item.get("images") or []), "kind": "Playlist"}


def parse_playlist_songs(data: dict) -> list[dict]:
	# Since 2026 Spotify calls each entry's song "item"; it used to be "track".
	songs = (parse_song(entry.get("item") or entry.get("track")) for entry in data.get("items") or [] if entry)
	return [song for song in songs if song]


def parse_playlists(data: dict) -> list[dict]:
	return [{"name": playlist.get("name", ""), "uri": playlist["uri"], "cover": biggest_image(playlist.get("images") or []),
		"owner": (playlist.get("owner") or {}).get("display_name") or "", "owner_id": (playlist.get("owner") or {}).get("id") or ""}
		for playlist in data.get("items") or [] if playlist and playlist.get("uri")]


def person_card(user_id: str, name: str, playlists: int) -> dict:
	"""A person for the search's cards; tapping it shows their playlists."""
	return {"name": name or user_id, "subtitle": f"{playlists} playlist{'s' if playlists != 1 else ''}",
		"uri": f"spotify:user:{user_id}", "cover": None, "kind": "Profile", "person": True}


def parse_embed_songs(html: str) -> list[dict]:
	"""The songs in Spotify's public playlist widget (at most 100; it has no covers per song)."""
	match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
	if not match:
		return []
	try:
		entity = json.loads(match.group(1))["props"]["pageProps"]["state"]["data"]["entity"]
	except (ValueError, KeyError, TypeError):   # Spotify changed the page
		return []
	return [{"title": track.get("title", ""), "artist": track.get("subtitle", ""), "cover": None, "uri": track["uri"],
		"length": minutes(track.get("duration") or 0)} for track in entity.get("trackList") or [] if track.get("uri")]


def heard_volume(spotify_percent: int) -> int:
	"""The volume as it sounds, 0-100, from the speaker's own volume (spotify_percent).

	spotifyd turns its volume into loudness on a decibel scale (60 dB range: amplitude
	10^(3 * (v - 1))), so below ~40% it's practically silent and everything happens at the top.
	Loudness as heard grows like amplitude^0.6, so this makes each step sound equally big."""
	if spotify_percent <= 0:
		return 0
	return round(100 * 10 ** (3 * DB_PER_DECADE_HEARD * (spotify_percent / 100 - 1)))


def spotify_volume(heard_percent: int) -> int:
	"""The opposite of heard_volume()."""
	if heard_percent <= 0:
		return 0
	return max(1, min(100, round(100 * (1 + math.log10(heard_percent / 100) / (3 * DB_PER_DECADE_HEARD)))))


def minutes(ms: int) -> str:
	seconds = ms // 1000
	return f"{seconds // 60}:{seconds % 60:02d}"


class SpotifyProvider(Provider):
	name = "spotify"
	title = "Spotify"
	nothing_to_show = "Spotify is not connected (see README.md)"

	def __init__(self, settings: dict, credentials_path: Path, default_seconds: float) -> None:
		self.credentials_path = credentials_path
		self.redirect_uri = settings.get("redirect_uri", "http://127.0.0.1:8080/spotify/callback")
		self.speaker = settings.get("speaker", "Francken TV")   # spotifyd on the TV PC (deploy/spotifyd.conf)
		self.show_when_idle = settings.get("show_when_idle", True)   # with Search and Playlists, to start music
		self.start_playlist = settings.get("start_playlist", "")   # played on start if there's nothing to resume
		self.start_step = "resume" if settings.get("play_on_start", True) else None   # see start_music()
		self.start_deadline = time.monotonic() + START_WAIT_SECONDS
		self.seconds = settings.get("seconds", default_seconds)
		self.refresh_seconds = settings.get("check_every_seconds", 5)
		self.playing: NowPlaying | None = None
		self.next: dict | None = None             # the next song in the queue
		self.next_fetched = (None, 0.0)           # (song id, time.monotonic()) of the last queue check
		self.playlists: list[dict] = []           # every playlist seen, to look up names
		self.playlist_pages: dict[int, tuple[float, list[dict], int]] = {}   # page -> (fetched, playlists, total)
		self.embed_songs: dict[str, list[dict]] = {}   # playlist id -> songs, for playlists by others
		self.found: dict[str, dict] = {}    # albums and playlists found by searching, by uri
		self.last_query = ""                # for "back to the search" from an album or playlist
		self.search_kind = "all"            # the chip chosen in the search: a key of SEARCH_KINDS
		self.search_view: dict = {}         # what the search page shows, to redraw it after adding to the queue
		self.library_cache: tuple[float, list[dict]] | None = None   # (fetched, all the account's playlists)
		self.person: dict = {}                    # the person whose playlists were shown last (a person_card)
		self.person_lists: dict[str, dict] = {}   # their playlists, by uri
		self.last_uri = ""                  # what played last: its playlist, album, ... or the song itself
		self.last_song: dict | None = None  # the last song that played (title, artist, cover, uri)
		self.last_played: dict | None = None   # last_uri described for the slide when nothing plays (see describe())
		self.last_checked = 0.0             # time.monotonic() of the last RECENTLY_PLAYED_URL request
		self.access_token: str | None = None
		self.token_expires = 0.0
		self.login_state: str | None = None
		self.scopes: set[str] | None = None   # what the saved login allows (None: not asked yet)
		self.volume_set: tuple[int, float] | None = None   # (volume, time.monotonic()) of the last volume button
		self.volume_lock = threading.Lock()
		self.jumps = 0   # how often the song jumped to another position (restart, seek): part of the slide's state
		self.lyrics: dict[str, Lyrics | None] = {}   # by song id; None: LRCLIB doesn't have them
		self.lyrics_lock = threading.Lock()   # the slide is redrawn every second: one lookup per song

	# ---- credentials and login ------------------------------------------------------------------

	def credentials(self) -> dict:
		try:
			return json.loads(self.credentials_path.read_text(encoding="utf-8"))
		except FileNotFoundError:
			return {}

	def save_credentials(self, credentials: dict) -> None:
		self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
		self.credentials_path.write_text(json.dumps(credentials, indent=1), encoding="utf-8")
		os.chmod(self.credentials_path, 0o600)   # only readable by this user

	def login_url(self) -> str | None:
		"""Where to send the browser to log in, or None if the app keys are missing."""
		client_id = self.credentials().get("client_id")
		if not client_id:
			return None
		self.login_state = secrets.token_urlsafe(16)
		return AUTHORIZE_URL + "?" + urlencode({"client_id": client_id, "response_type": "code",
			"redirect_uri": self.redirect_uri, "scope": SCOPES, "state": self.login_state})

	def finish_login(self, code: str, state: str) -> None:
		if not self.login_state or state != self.login_state:
			raise ValueError("this login link has expired; start again at /spotify/login")
		self.login_state = None
		tokens = self.request_token({"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri})
		self.save_credentials({**self.credentials(), "refresh_token": tokens["refresh_token"]})
		log.info("Connected to Spotify")

	def request_token(self, form: dict) -> dict:
		credentials = self.credentials()
		response = requests.post(TOKEN_URL, data=form, auth=(credentials["client_id"], credentials["client_secret"]), timeout=20)
		response.raise_for_status()
		tokens = response.json()
		self.access_token = tokens["access_token"]
		self.token_expires = time.monotonic() + tokens.get("expires_in", 3600) - 60
		if "scope" in tokens:
			self.scopes = set(tokens["scope"].split())
		return tokens

	@property
	def connected(self) -> bool:
		return bool(self.credentials().get("refresh_token"))

	# ---- what's playing -------------------------------------------------------------------------

	def api(self, method: str, url: str, **kwargs) -> requests.Response:
		"""A Web API request with a fresh access token. Raises for errors, except 401/403/404 (see callers)."""
		if self.access_token is None or time.monotonic() > self.token_expires:
			tokens = self.request_token({"grant_type": "refresh_token", "refresh_token": self.credentials()["refresh_token"]})
			if "refresh_token" in tokens:   # Spotify sometimes hands out a new one
				self.save_credentials({**self.credentials(), "refresh_token": tokens["refresh_token"]})
		response = requests.request(method, url, headers={"Authorization": f"Bearer {self.access_token}"}, timeout=20, **kwargs)
		if response.status_code == 401:
			self.access_token = None   # expired early: get a new one next time
		if response.status_code not in (401, 403, 404):
			response.raise_for_status()
		return response

	def refresh(self, now: datetime) -> None:
		if not self.connected:
			self.playing = None
			return
		response = self.api("GET", PLAYING_URL)
		if response.status_code >= 400:
			return
		before = self.playing
		self.playing = parse_playing(response.json(), time.monotonic()) if response.status_code == 200 and response.content else None
		if before and self.playing and before.id == self.playing.id and abs(self.playing.progress_ms - before.progress()) > JUMP_MS:
			self.jumps += 1   # restarted (the ⏮ button) or moved within the song: the slide redraws (see view())
		if self.playing and self.volume_set and time.monotonic() - self.volume_set[1] < VOLUME_SETTLE_SECONDS:
			self.playing.volume = self.volume_set[0]   # Spotify takes a moment to report a new volume
		if self.playing:
			self.remember(self.playing.context, {"title": self.playing.title, "artist": self.playing.artist,
				"cover": self.playing.cover, "uri": self.playing.uri})
		elif not self.start_step:   # (on start the music is started first)
			self.refresh_last_played()
		if self.playing is None:
			self.next = None
		elif self.next_fetched[0] != self.playing.id or time.monotonic() - self.next_fetched[1] > QUEUE_EVERY_SECONDS:
			self.refresh_next()
		if self.start_step:
			self.start_music()

	def start_music(self) -> None:
		"""When the slideshow starts: if nothing plays, start the music on our own speaker. First resume
		the account's last session; if that doesn't play anything, play start_playlist (if set).
		Waits for the speaker (spotifyd may start later at boot), at most START_WAIT_SECONDS."""
		if self.playing and self.playing.is_playing:
			if self.start_step == "resume":
				log.info("Spotify already plays on %s: not starting anything", self.playing.device)
			self.start_step = None
			return
		if time.monotonic() > self.start_deadline:
			log.warning("Could not start the music: the %s speaker didn't show up", self.speaker)
			self.start_step = None
			return
		speaker = self.speaker_id()
		if speaker is None:
			return   # not there yet: try again at the next refresh
		if self.start_step == "resume":
			if self.playing and self.playing.device == self.speaker:   # paused here: just play (moving it here does nothing)
				response = self.api("PUT", PLAY_URL, params={"device_id": speaker})
			else:   # the last session (played elsewhere, or nothing active): move it here and play
				response = self.api("PUT", PLAYER_URL, json={"device_ids": [speaker], "play": True})
			log.info("Started the music on %s (the last session): %s", self.speaker, response.status_code)
			self.start_step = "playlist"   # next refresh: still nothing playing? then the playlist
		else:
			if self.start_playlist:
				response = self.api("PUT", PLAY_URL, params={"device_id": speaker}, json={"context_uri": self.start_playlist})
				log.info("Started %s on %s: %s", self.start_playlist, self.speaker, response.status_code)
			elif self.playing:   # something to resume after all (moving it here took a moment)
				response = self.api("PUT", PLAY_URL, params={"device_id": speaker})
				log.info("Resumed the music on %s: %s", self.speaker, response.status_code)
			self.start_step = None

	def remember(self, context: str, song: dict | None) -> None:
		if song and song.get("uri"):
			self.last_song = song
		self.last_uri = context or (song or {}).get("uri", "")

	def refresh_last_played(self) -> None:
		"""Nothing plays: find out what played last (if it didn't play while we watched), for the slide."""
		if not self.last_uri and time.monotonic() - self.last_checked > LAST_PLAYED_EVERY_SECONDS:
			self.last_checked = time.monotonic()
			response = self.api("GET", RECENTLY_PLAYED_URL, params={"limit": 1})
			items = response.json().get("items") or [] if response.status_code == 200 else []
			if items:
				self.remember((items[0].get("context") or {}).get("uri") or "", parse_song(items[0]["track"]))
		if self.last_uri and (self.last_played or {}).get("uri") != self.last_uri:
			self.last_played = self.describe(self.last_uri)

	def describe(self, uri: str) -> dict:
		"""The name, cover and Play button of what played last: a playlist, album, artist or podcast, or a song
		(played on its own, or from Liked Songs, which the Web API can't play as a whole)."""
		song = self.last_song or {}
		kind = uri.split(":")[1]
		if kind not in ("playlist", "album", "artist", "show"):
			liked = uri.endswith(":collection")
			return {"uri": uri, "name": "Liked Songs" if liked else song["title"], "cover": song["cover"],
				"subtitle": f"{song['title']} \u00b7 {song['artist']}" if liked else song["artist"],
				"action": "play_song", "value": song["uri"], "shuffle": False}
		data = self.api("GET", f"{API}/{kind}s/{uri.rsplit(':', 1)[-1]}").json()
		subtitle = {"playlist": f"By {(data.get('owner') or {}).get('display_name', '')}", "artist": "Artist", "show": "Podcast",
			"album": ", ".join(a["name"] for a in data.get("artists") or [])}[kind]
		goes_on = kind in ("playlist", "album") and song.get("uri")   # from the last song
		return {"uri": uri, "name": data["name"], "subtitle": subtitle, "cover": card_image(data.get("images") or []),
			"action": "play_song" if goes_on else "play", "value": f"{song['uri']}|{uri}" if goes_on else uri,
			"shuffle": kind in ("playlist", "album")}

	def refresh_next(self) -> None:
		try:
			response = self.api("GET", QUEUE_URL)
			self.next = parse_next(response.json()) if response.status_code == 200 and response.content else None
		except requests.RequestException as error:   # not worth failing the whole refresh for
			log.warning("Could not get the Spotify queue: %s", error)
		self.next_fetched = (self.playing.id if self.playing else None, time.monotonic())

	def fetch_playlists(self, page: int = 0) -> tuple[list[dict], int]:
		"""One page of the account's playlists, and how many there are."""
		cached = self.playlist_pages.get(page)
		if cached and time.monotonic() - cached[0] < PLAYLISTS_EVERY_SECONDS:
			return cached[1], cached[2]
		response = self.api("GET", PLAYLISTS_URL, params={"limit": PLAYLISTS_PER_PAGE, "offset": page * PLAYLISTS_PER_PAGE})
		if response.status_code == 403:
			raise PermissionError("needs a new login")
		if response.status_code != 200:
			return [], 0
		playlists, total = parse_playlists(response.json()), response.json().get("total", 0)
		self.playlist_pages[page] = (time.monotonic(), playlists, total)
		known = {playlist["uri"] for playlist in self.playlists}
		self.playlists += [playlist for playlist in playlists if playlist["uri"] not in known]
		return playlists, total

	def library(self) -> list[dict]:
		"""All the account's playlists (at most LIBRARY_MAX), to find the people who made them."""
		if self.library_cache and time.monotonic() - self.library_cache[0] < PLAYLISTS_EVERY_SECONDS:
			return self.library_cache[1]
		playlists: list[dict] = []
		offset = 0
		while offset < LIBRARY_MAX:
			response = self.api("GET", PLAYLISTS_URL, params={"limit": 50, "offset": offset})
			if response.status_code != 200:
				break
			data = response.json()
			playlists += parse_playlists(data)
			offset += len(data.get("items") or [])
			if not data.get("items") or offset >= data.get("total", 0):
				break
		self.library_cache = (time.monotonic(), playlists)
		known = {playlist["uri"] for playlist in self.playlists}
		self.playlists += [playlist for playlist in playlists if playlist["uri"] not in known]
		return playlists

	def find_people(self, query: str) -> list[dict]:
		"""The makers of the account's playlists whose name (or username) has the query in it."""
		wanted = query.strip().casefold()
		people: dict[tuple[str, str], int] = {}   # (username, name) -> number of playlists
		for playlist in self.library():
			if wanted in playlist["owner"].casefold() or wanted in playlist["owner_id"].casefold():
				owner = (playlist["owner_id"], playlist["owner"])
				people[owner] = people.get(owner, 0) + 1
		return [person_card(user_id, name, count) for (user_id, name), count in people.items()]

	def fetch_songs(self, playlist_uri: str, page: int) -> tuple[list[dict], int]:
		"""One page of a playlist's songs, and the number of songs in it."""
		playlist_id = playlist_uri.rsplit(":", 1)[-1]
		if playlist_uri.startswith("spotify:album:"):   # an album (from the search): its songs can always be read
			response = self.api("GET", f"{API}/albums/{playlist_id}/tracks",
				params={"limit": SONGS_PER_PAGE, "offset": page * SONGS_PER_PAGE})
			response.raise_for_status()
			data = response.json()
			return [song for song in map(parse_song, data.get("items") or []) if song], data.get("total", 0)
		response = self.api("GET", f"{API}/playlists/{playlist_id}/items",
			params={"limit": SONGS_PER_PAGE, "offset": page * SONGS_PER_PAGE})
		if response.status_code in (401, 403, 404):
			# Spotify only lets apps read the account's own playlists: get the others from the public widget.
			if playlist_id not in self.embed_songs:
				embed = requests.get(EMBED_URL.format(id=playlist_id), headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
				embed.raise_for_status()
				self.embed_songs[playlist_id] = parse_embed_songs(embed.text)
			songs = self.embed_songs[playlist_id]
			if not songs:
				raise PermissionError("can't read this playlist")
			return songs[page * SONGS_PER_PAGE:(page + 1) * SONGS_PER_PAGE], len(songs)
		data = response.json()
		return parse_playlist_songs(data), data.get("total", 0)

	def search(self, query: str, kind: str = "all") -> tuple[list[dict], list[dict]]:
		"""Songs, and cards (albums, playlists and people), matching the query, for one of the chips (SEARCH_KINDS)."""
		if kind == "people":
			cards = self.find_people(query)[:SEARCH_CARDS_ONLY]
			self.found.update({card["uri"]: card for card in cards})
			return [], cards
		response = self.api("GET", SEARCH_URL, params={"q": query, "type": SEARCH_KINDS[kind], "limit": SEARCH_RESULTS})
		if response.status_code >= 400:
			raise PermissionError("search failed")
		data = response.json()
		songs = [song for song in map(parse_song, (data.get("tracks") or {}).get("items") or []) if song]
		albums = [album for album in map(parse_album, (data.get("albums") or {}).get("items") or []) if album]
		playlists = [playlist for playlist in map(parse_found_playlist, (data.get("playlists") or {}).get("items") or []) if playlist]
		if kind == "all":   # like the desktop app: a few of each; if there are few playlists, more albums
			people = self.find_people(query)[:SEARCH_CARDS // 2]
			room = SEARCH_CARDS - len(people)
			cards = albums[:max(room // 2, room - len(playlists))] + playlists
			cards = people + cards[:room]
		else:
			cards = (albums + playlists)[:SEARCH_CARDS_ONLY]
		self.found.update({card["uri"]: card for card in cards})
		return songs, cards

	def view(self) -> dict:
		playing = self.playing
		progress = playing.progress()
		return {
			# A new song, pausing/resuming, a jump in the song or a new next song (e.g. one added to the queue)
			# redraws the slide (see refresh() in player.js).
			"state": f"{playing.id} {'playing' if playing.is_playing else 'paused'} {self.jumps} {(self.next or {}).get('uri', '')}",
			"title": playing.title, "artist": playing.artist, "album": playing.album,
			"cover": playing.cover, "is_playing": playing.is_playing, "next": self.next,
			"volume": None if playing.volume is None else self.shown_volume(playing),
			"device": playing.device, "on_speaker": playing.device == self.speaker, "speaker": self.speaker,
			"elapsed": minutes(progress), "total": minutes(playing.duration_ms),
			# For the bar and the clock, which the browser moves on by itself (see "Spotify" in style.css).
			"elapsed_seconds": progress // 1000, "total_seconds": playing.duration_ms // 1000,
			"percent": round(progress / playing.duration_ms * 100, 2) if playing.duration_ms else 0,
		}

	def collection_name(self, uri: str) -> str:
		"""The name of a playlist or album we've shown, for messages like "Playing ..."."""
		if uri in self.found:
			return self.found[uri]["name"]
		if uri in self.person_lists:
			return self.person_lists[uri]["name"]
		return next((p["name"] for p in self.playlists if p["uri"] == uri), "the playlist")

	def shown_volume(self, playing: NowPlaying) -> int:
		"""The volume bar: as it sounds on our own speaker; other players as Spotify reports them."""
		return heard_volume(playing.volume) if playing.device == self.speaker else playing.volume

	def current_view(self) -> dict:
		if self.playing:
			return self.view()
		# Nothing playing: what played last, or pick something.
		last = self.last_played if self.last_played and self.last_played["uri"] == self.last_uri else None
		return {"state": "idle " + (last or {}).get("uri", ""), "idle": True, "speaker": self.speaker, "last": last}

	def now_playing(self) -> Slide:
		# Checked every second, so a new song (or the music stopping) shows up while the slide is on screen.
		return Slide("spotify.html", self.seconds, self.current_view(),
			update=lambda now: self.current_view(), refresh_seconds=1)

	def song_lyrics(self, playing: NowPlaying) -> Lyrics | None | str:
		"""The playing song's lyrics (looked up once per song), None if there are none, or "error"
		when LRCLIB can't be reached (tried again when the view is drawn again)."""
		with self.lyrics_lock:
			if playing.id not in self.lyrics:
				try:
					self.lyrics[playing.id] = find_lyrics(playing.title, playing.artist, playing.album, playing.duration_ms // 1000)
				except requests.RequestException as error:
					log.warning("Could not get the lyrics of %s: %s", playing.title, error)
					return "error"
				if len(self.lyrics) > 50:   # only recent songs
					del self.lyrics[next(iter(self.lyrics))]
			return self.lyrics[playing.id]

	def lyrics_view(self) -> dict:
		if not self.playing:
			return {"state": "lyrics idle", "idle": True}
		lyrics = self.song_lyrics(self.playing)
		return {**self.view(), "state": "lyrics " + self.view()["state"],
			"lyrics": None if lyrics == "error" else lyrics, "lyrics_error": lyrics == "error",
			"progress_seconds": round(self.playing.progress() / 1000, 2)}

	def lyrics_slide(self) -> Slide:
		# Redrawn when the song changes, pauses or jumps (data-state); the lit-up line moves on by
		# itself in between (widgets.js).
		return Slide("spotify_lyrics.html", self.seconds, self.lyrics_view(), update=lambda now: self.lyrics_view(), refresh_seconds=1)

	def speaker_id(self) -> str | None:
		"""The Spotify Connect id of the TV PC's own speaker (spotifyd), if it's running."""
		response = self.api("GET", DEVICES_URL)
		devices = response.json().get("devices", []) if response.status_code == 200 else []
		return next((device["id"] for device in devices if device.get("name") == self.speaker), None)

	@property
	def needs_new_login(self) -> bool:
		"""The saved login is older than the buttons: it may only read what's playing."""
		return self.scopes is not None and not set(SCOPES.split()) <= self.scopes

	def command(self, method: str, url: str, start: bool = False, **kwargs) -> str | None:
		"""Tell the Spotify player to do something; returns what went wrong, or None.
		start: if no player is active, play on the TV PC's own speaker."""
		if self.needs_new_login:
			return NEW_LOGIN_MESSAGE
		try:
			response = self.api(method, url, **kwargs)
			if response.status_code == 404 and start and (speaker := self.speaker_id()):
				response = self.api(method, url, params={**kwargs.pop("params", {}), "device_id": speaker}, **kwargs)
		except requests.RequestException as error:
			log.warning("Spotify command %s failed: %s", url, error)
			return "Spotify can't be reached right now"
		if response.status_code == 404:
			return f"No Spotify player is active, and the {self.speaker} speaker isn't running"
		if response.status_code in (401, 403):
			return NEW_LOGIN_MESSAGE if self.needs_new_login else "Spotify doesn't allow this: it needs Spotify Premium"
		return None

	def catch_up(self, now: datetime) -> None:
		"""After a command: ask what's playing until Spotify reports a change (a new song, paused or
		playing), at most CATCH_UP_SECONDS, so the slide shows the result as soon as it's there."""
		before = self.playing
		key = (before.id, before.is_playing, self.jumps) if before else None
		for _ in range(round(CATCH_UP_SECONDS / CATCH_UP_EVERY)):
			time.sleep(CATCH_UP_EVERY)
			try:
				self.refresh(now)
			except requests.RequestException:
				break   # the background refresh catches up within a few seconds
			if self.playing and (self.playing.id, self.playing.is_playing, self.jumps) != key:
				break
		self.playing = self.playing or before   # Spotify may not report the new song yet

	def slides(self, now: datetime) -> list[Slide]:
		if not self.connected:
			return []
		if (self.playing and self.playing.is_playing) or self.show_when_idle:
			return [self.now_playing()]
		return []   # nothing playing (and show_when_idle is off): no slide

	def shortcut_slide(self, now: datetime) -> Slide | None:
		# Also when nothing plays: the shortcut is a quick way to start the music.
		return self.now_playing() if self.connected else None

	def action(self, name: str, values: list[str], now: datetime) -> tuple[Slide | None, str | None]:
		"""'playlists' shows the playlists, 'songs' one playlist's songs, 'search' finds songs, playlists, albums
		and people ('search_kind' picks a chip: all, songs, playlists, albums or people), 'person' someone's
		playlists, 'lyrics' the lyrics;
		'play' plays a playlist (values = [its uri]), 'play_song' a song, 'queue' adds one; 'back' returns;
		'previous', 'skip', 'toggle' (pause/play), 'volume_up' and 'volume_down' control the music."""
		if name == "playlists":
			page = int(values[0]) if values and values[0].isdigit() else 0
			try:
				playlists, total = self.fetch_playlists(page)
			except PermissionError:
				return None, NEW_LOGIN_MESSAGE
			except requests.RequestException as error:
				log.warning("Could not get the Spotify playlists: %s", error)
				return None, "Spotify can't be reached right now"
			if not playlists:
				return None, "No playlists found on this Spotify account"
			return Slide("spotify_playlists.html", self.seconds, {"playlists": playlists, "page": page,
				"pages": max(1, -(-total // PLAYLISTS_PER_PAGE))}), None
		if name == "songs" and values:   # value: "playlist or album uri|page" (a button sends one value)
			uri, _, page_text = values[0].partition("|")
			page = int(page_text) if page_text.isdigit() else 0
			if self.needs_new_login:
				return None, NEW_LOGIN_MESSAGE
			try:
				songs, total = self.fetch_songs(uri, page)
				readable = True
			except PermissionError:
				# Spotify only lets apps read the songs of the account's own playlists; others can still be played.
				songs, total, readable = [], 0, False
			except requests.RequestException as error:
				log.warning("Could not get the songs of %s: %s", uri, error)
				return None, "Spotify can't be reached right now"
			if uri in self.found:   # from the search: back to it
				playlist = self.found[uri]
				back = {"action": "search", "value": self.last_query, "label": "Search"}
			elif uri in self.person_lists:   # from someone's playlists: back to them
				playlist = self.person_lists[uri]
				back = {"action": "person", "value": self.person["uri"], "label": self.person["name"]}
			else:
				playlist = next((p for p in self.playlists if p["uri"] == uri), {"name": "Playlist", "uri": uri, "cover": None})
				back = {"action": "playlists", "value": "", "label": "Playlists"}
			pages = max(1, -(-total // SONGS_PER_PAGE))
			return Slide("spotify_songs.html", self.seconds, {"playlist": playlist, "songs": songs, "readable": readable,
				"back": back, "page": page, "pages": pages, "first_number": page * SONGS_PER_PAGE + 1}), None
		if name == "person" and values:   # value: "spotify:user:id|page"; their playlists in the account's library
			uri, _, page_text = values[0].partition("|")
			page = int(page_text) if page_text.isdigit() else 0
			person = self.found[uri]
			theirs = [playlist for playlist in self.library() if playlist["owner_id"] == uri.rsplit(":", 1)[-1]]
			playlists, total = theirs[page * PLAYLISTS_PER_PAGE:(page + 1) * PLAYLISTS_PER_PAGE], len(theirs)
			self.person = person
			self.person_lists.update({playlist["uri"]: playlist for playlist in playlists})
			return Slide("spotify_playlists.html", self.seconds, {"playlists": playlists, "page": page,
				"pages": max(1, -(-total // PLAYLISTS_PER_PAGE)), "person": person, "page_action": "person", "page_prefix": uri + "|",
				"back": {"action": "search", "value": self.last_query, "label": "Search"}}), None
		if name in ("search", "search_kind"):   # search: values = [typed text], empty: just the keyboard;
			if name == "search_kind":           # search_kind: values = [a chip], the last search again
				self.search_kind = values[0] if values and values[0] in SEARCH_KINDS else "all"
				query = self.last_query
			else:
				query = values[0].strip() if values else ""
			kind = self.search_kind
			songs: list[dict] = []
			cards: list[dict] = []
			self.last_query = query
			if query:
				try:
					songs, cards = self.search(query, kind)
				except (PermissionError, requests.RequestException) as error:
					log.warning("Spotify search for %r failed: %s", query, error)
					return None, "Searching Spotify failed, try again"
			self.search_view = {"query": query, "songs": songs, "cards": cards, "searched": bool(query),
				"kind": kind, "kinds": [("all", "All"), ("songs", "Songs"), ("playlists", "Playlists"), ("albums", "Albums"), ("people", "People")],
				"rows": [list("1234567890"), list("QWERTYUIOP"), list("ASDFGHJKL"), list("ZXCVBNM")], "queued": set()}
			return Slide("spotify_search.html", self.seconds, self.search_view), None
		if name == "play_song" and values:   # value: "song uri" or "song uri|playlist uri" (to go on with the playlist)
			song, _, playlist = values[0].partition("|")
			body = {"context_uri": playlist, "offset": {"uri": song}} if playlist else {"uris": [song]}
			error = self.command("PUT", PLAY_URL, start=True, json=body)
			if error:
				return None, error
			self.catch_up(now)
			return self.now_playing(), None
		if name == "queue" and values:   # from the search page: it's redrawn with a popup, and a tick on the song
			error = self.command("POST", QUEUE_ADD_URL, params={"uri": values[0]})
			if not error:
				self.next_fetched = (None, 0.0)   # the next song may have changed
				self.search_view.setdefault("queued", set()).add(values[0])
			song = next((song for song in self.search_view.get("songs", []) if song["uri"] == values[0]), None)
			message = error or (f"Added {song['title']} to the queue" if song else "Added to the queue")
			if not self.search_view:
				return None, message
			return Slide("spotify_search.html", self.seconds, self.search_view | {"message": message}), message
		if name == "shuffle" and values:   # a playlist in random order, starting at a random song
			error = self.command("PUT", PLAY_URL, start=True, json={"context_uri": values[0]})
			error = error or self.command("PUT", SHUFFLE_URL, params={"state": "true"})
			error = error or self.command("POST", NEXT_URL)
			if error:
				return None, error
			self.catch_up(now)
			return self.now_playing(), f"Shuffling {self.collection_name(values[0])}"
		if name == "play" and values:
			error = self.command("PUT", PLAY_URL, start=True, json={"context_uri": values[0]})
			if error:
				return None, error
			self.catch_up(now)
			return self.now_playing(), f"Playing {self.collection_name(values[0])}"
		if name == "here":   # move the music to the TV PC's own speaker
			try:
				speaker = self.speaker_id()
			except requests.RequestException:
				speaker = None
			if speaker is None:
				return None, f"The {self.speaker} speaker isn't running (see the README, \"Spotify\")"
			error = self.command("PUT", PLAYER_URL, json={"device_ids": [speaker], "play": True})
			if error:
				return None, error
			self.catch_up(now)
			return self.now_playing(), f"Playing on {self.speaker}"
		if name == "lyrics":
			return self.lyrics_slide(), None
		if name in ("previous", "skip", "toggle") and self.playing:
			if name == "toggle":
				error = self.command("PUT", PAUSE_URL if self.playing.is_playing else PLAY_URL, start=True)
			else:
				error = self.command("POST", PREVIOUS_URL if name == "previous" else NEXT_URL)
			if error:
				return None, error
			self.catch_up(now)
			# The lyrics view's buttons send "lyrics" along, so it stays the lyrics view.
			return (self.lyrics_slide() if values[:1] == ["lyrics"] else self.now_playing()), None
		if name in ("volume_up", "volume_down") and self.playing and self.playing.volume is not None:
			step = VOLUME_STEP if name == "volume_up" else -VOLUME_STEP
			with self.volume_lock:   # quick taps arrive together: one after another, each from the last one
				if self.playing.device == self.speaker:   # steps that sound equally big, see heard_volume()
					heard = round(heard_volume(self.playing.volume) / VOLUME_STEP) * VOLUME_STEP
					volume = spotify_volume(max(0, min(100, heard + step)))
				else:   # another player (e.g. a web player) has its own volume curve
					volume = max(0, min(100, self.playing.volume + step))
				error = self.command("PUT", f"{VOLUME_URL}?volume_percent={volume}")
				if error:
					return None, error
				self.playing.volume = volume
				self.volume_set = (volume, time.monotonic())
			return None, None   # the volume bar is updated in place (data-live), so the slide doesn't restart
		return self.now_playing(), None
