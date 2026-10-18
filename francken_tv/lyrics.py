"""Song lyrics from LRCLIB (lrclib.net): a free, open lyrics database, no key needed.

Many songs have synced lyrics (a time for every line: the Spotify lyrics view lights up the line being
sung); others only plain text, and some none. A song is looked up by its exact title, artist, album and
length first, then by a search on the title and artist (Spotify's titles often carry extras such as
"- Remastered 2011" that LRCLIB doesn't have), taking the result closest in length.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import requests

log = logging.getLogger(__name__)

GET_URL = "https://lrclib.net/api/get"
SEARCH_URL = "https://lrclib.net/api/search"
HEADERS = {"User-Agent": "FranckenTV-slideshow/1.0 (the TV in the T.F.V. 'Professor Francken' room; https://professorfrancken.nl)"}
LENGTH_MARGIN = 5   # seconds: a search result this close in length is the same recording
LRC_LINE = re.compile(r"^\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)$")
TITLE_EXTRAS = re.compile(r"\s+-\s+.*$|\s*[(\[](?:feat|ft|with|from|remaster|live|mono|stereo|take|version|edit)[^)\]]*[)\]]", re.I)


@dataclass
class Line:
	time: float | None   # seconds into the song; None for plain lyrics
	text: str


@dataclass
class Lyrics:
	lines: list[Line] = field(default_factory=list)
	synced: bool = False
	instrumental: bool = False


def parse_lrc(lrc: str) -> list[Line]:
	"""'[00:10.81] Them that's got shall have' lines, in time order; empty lines become pauses."""
	lines = []
	for raw in lrc.splitlines():
		match = LRC_LINE.match(raw.strip())
		if match:
			minutes, seconds, text = match.groups()
			lines.append(Line(round(int(minutes) * 60 + float(seconds), 2), text.strip()))
	return sorted(lines, key=lambda line: line.time)


def from_record(record: dict) -> Lyrics:
	if record.get("instrumental"):
		return Lyrics(instrumental=True)
	if record.get("syncedLyrics"):
		lines = parse_lrc(record["syncedLyrics"])
		if lines:
			return Lyrics(lines, synced=True)
	plain = record.get("plainLyrics") or ""
	return Lyrics([Line(None, text.strip()) for text in plain.splitlines()])


def simple_title(title: str) -> str:
	"""'God Bless the Child - Take 1' -> 'God Bless the Child'; '... (feat. X)' -> '...'"""
	return TITLE_EXTRAS.sub("", title).strip() or title


def find_lyrics(title: str, artist: str, album: str, seconds: int) -> Lyrics | None:
	"""The song's lyrics, or None if LRCLIB doesn't have them. Raises when LRCLIB can't be reached."""
	first_artist = artist.split(",")[0].strip()
	response = requests.get(GET_URL, headers=HEADERS, timeout=10,
		params={"track_name": title, "artist_name": first_artist, "album_name": album, "duration": seconds})
	if response.status_code == 200:
		return from_record(response.json())
	if response.status_code != 404:
		response.raise_for_status()
	response = requests.get(SEARCH_URL, headers=HEADERS, timeout=10,
		params={"track_name": simple_title(title), "artist_name": first_artist})
	response.raise_for_status()
	close = [record for record in response.json() if abs((record.get("duration") or 0) - seconds) <= LENGTH_MARGIN]
	if not close:
		return None
	# Synced lyrics first, then the closest in length.
	best = min(close, key=lambda record: (not record.get("syncedLyrics"), abs((record.get("duration") or 0) - seconds)))
	return from_record(best)
