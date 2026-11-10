"""A lyric video of the song playing on Spotify: the line being sung, full screen and big, each line in
its own typographic style and colours, the words popping in about as they're sung
(templates/slides/lyric_video.html, data-lyric-video in static/widgets.js).

Needs synced lyrics (a time for every line) from LRCLIB, looked up by the Spotify slide's lyrics view
(lyrics.py, SpotifyProvider.song_lyrics()); refresh() looks them up as soon as a song starts, so the
slide is ready when its turn comes. In the round only while a song plays that has synced lyrics,
and only if some of them are still to come; the shortcut and the menu preview show it anyway (with
the song's title when there are no lyrics).
"""

from __future__ import annotations

from datetime import datetime

from ..lyrics import Lyrics
from ..slides import Provider, Slide
from .spotify import SpotifyProvider


class LyricVideoProvider(Provider):
	name = "lyric_video"
	title = "Lyric video"
	nothing_to_show = "No song with synced lyrics is playing"

	def __init__(self, settings: dict, spotify: SpotifyProvider):
		self.spotify = spotify
		self.seconds = settings.get("seconds", 30)
		self.refresh_seconds = settings.get("check_every_seconds", 5)

	def refresh(self, now: datetime) -> None:
		playing = self.spotify.playing
		if playing and playing.is_playing:
			self.spotify.song_lyrics(playing)   # looked up once per song

	def view(self) -> dict:
		playing = self.spotify.playing or self.spotify.last
		lyrics = self.spotify.song_lyrics(playing)
		lines = lyrics.lines if isinstance(lyrics, Lyrics) and lyrics.synced else []
		base = self.spotify.view()
		return {**base, "lines": lines, "progress_seconds": round(playing.progress() / 1000, 2),
			# Redrawn when the song changes, pauses or jumps, or when its lyrics arrive.
			"state": f"lyric-video {len(lines)} {base['state']}"}

	def slide(self) -> Slide:
		return Slide("lyric_video.html", self.seconds, self.view(), update=lambda now: self.view(), refresh_seconds=1)

	def slides(self, now: datetime) -> list[Slide]:
		playing = self.spotify.playing
		if not (self.spotify.connected and playing and playing.is_playing):
			return []
		lyrics = self.spotify.cached_lyrics(playing)   # slides() must be fast: refresh() looked them up
		if not (lyrics and lyrics.synced):
			return []
		# Only if something is sung while the slide is on screen (not during the outro).
		progress = playing.progress() / 1000
		if not any(line.text and progress - 5 <= line.time <= progress + self.seconds - 5 for line in lyrics.lines):
			return []
		return [self.slide()]

	def shortcut_slide(self, now: datetime) -> Slide | None:
		if not (self.spotify.connected and (self.spotify.playing or self.spotify.last)):
			return None
		return self.slide()

	def has_slide(self, now: datetime) -> bool:
		return self.spotify.connected and bool(self.spotify.playing or self.spotify.last)   # without looking up lyrics
