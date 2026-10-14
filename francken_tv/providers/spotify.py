"""What's playing on Spotify: title, artist, album cover and progress (templates/slides/spotify.html).

Uses Spotify's Web API. One-time setup (see README, "Spotify"):
1. Create an app at https://developer.spotify.com/dashboard with redirect URI
   http://127.0.0.1:8080/spotify/callback, and put its keys in ~/.config/slideshow/spotify.json:
   {"client_id": "...", "client_secret": "..."}
2. Open http://127.0.0.1:8080/spotify/login on the TV PC and log in with Spotify.
   The slideshow then adds a refresh token to that file; no password is stored.
The slide only appears while something is playing.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import requests

from ..slides import Provider, Slide

log = logging.getLogger(__name__)

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
PLAYING_URL = "https://api.spotify.com/v1/me/player/currently-playing?additional_types=episode"
SCOPES = "user-read-currently-playing user-read-playback-state"


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
	cover = max(images, key=lambda image: image.get("width") or 0)["url"] if images else None
	return NowPlaying(
		id=item.get("id") or item.get("uri", ""), title=item.get("name", ""), artist=artist, album=album, cover=cover,
		duration_ms=item.get("duration_ms", 0), progress_ms=data.get("progress_ms") or 0,
		is_playing=bool(data.get("is_playing")), fetched_at=fetched_at,
	)


def minutes(ms: int) -> str:
	seconds = ms // 1000
	return f"{seconds // 60}:{seconds % 60:02d}"


class SpotifyProvider(Provider):
	name = "spotify"

	def __init__(self, settings: dict, credentials_path: Path, default_seconds: float) -> None:
		self.credentials_path = credentials_path
		self.redirect_uri = settings.get("redirect_uri", "http://127.0.0.1:8080/spotify/callback")
		self.seconds = settings.get("seconds", default_seconds)
		self.refresh_seconds = settings.get("check_every_seconds", 5)
		self.playing: NowPlaying | None = None
		self.access_token: str | None = None
		self.token_expires = 0.0
		self.login_state: str | None = None

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
		return tokens

	@property
	def connected(self) -> bool:
		return bool(self.credentials().get("refresh_token"))

	# ---- what's playing -------------------------------------------------------------------------

	def refresh(self, now: datetime) -> None:
		if not self.connected:
			self.playing = None
			return
		if self.access_token is None or time.monotonic() > self.token_expires:
			tokens = self.request_token({"grant_type": "refresh_token", "refresh_token": self.credentials()["refresh_token"]})
			if "refresh_token" in tokens:   # Spotify sometimes hands out a new one
				self.save_credentials({**self.credentials(), "refresh_token": tokens["refresh_token"]})
		response = requests.get(PLAYING_URL, headers={"Authorization": f"Bearer {self.access_token}"}, timeout=20)
		if response.status_code == 401:
			self.access_token = None   # expired early: get a new one next time
			return
		response.raise_for_status()
		self.playing = parse_playing(response.json(), time.monotonic()) if response.status_code == 200 and response.content else None

	def view(self) -> dict:
		playing = self.playing
		progress = playing.progress()
		return {
			"track": playing.id, "title": playing.title, "artist": playing.artist, "album": playing.album,
			"cover": playing.cover, "is_playing": playing.is_playing,
			"elapsed": minutes(progress), "total": minutes(playing.duration_ms),
			"percent": round(progress / playing.duration_ms * 100, 2) if playing.duration_ms else 0,
		}

	def slides(self, now: datetime) -> list[Slide]:
		if self.playing is None or not self.playing.is_playing:
			return []   # nothing playing: no slide
		# Redrawn every second: the progress moves on, and a new song shows up while the slide is on screen.
		# If the music stops meanwhile, the last song stays on screen.
		last = self.view()
		return [Slide("spotify.html", self.seconds, last,
			update=lambda now: self.view() if self.playing else last, refresh_seconds=1)]
