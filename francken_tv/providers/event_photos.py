"""Random photos from the most recent events, from the Francken Nextcloud.

Albums live in <albums_folder>/<year>/<YYYY-MM-DD>-<event name>/. A year folder can contain
albums from the previous year, so albums are sorted by the date in their name.
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from PIL import Image

from ..config import project_path
from ..media import IMAGE_EXTENSIONS
from ..nextcloud import Entry, Nextcloud, load_credentials
from ..slides import Provider, Slide, media_url

log = logging.getLogger(__name__)

ALBUM_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})[-_ ]*(.*)$")


@dataclass
class Album:
	path: str
	day: date
	title: str


@dataclass
class Photo:
	path: Path
	album: Album
	portrait: bool = False


def is_portrait(path: Path) -> bool:
	try:
		with Image.open(path) as image:
			return image.height > image.width
	except OSError:
		return False


def parse_album(entry: Entry) -> Album | None:
	match = ALBUM_NAME.match(entry.name)
	if not entry.is_folder or not match:
		return None
	try:
		day = date.fromisoformat(match.group(1))
	except ValueError:
		return None
	title = re.sub(r"[-_]+", " ", match.group(2)).strip()
	return Album(entry.path, day, title)


def most_recent_albums(entries: list[Entry], today: date, count: int) -> list[Album]:
	albums = [album for entry in entries if (album := parse_album(entry)) and album.day <= today]
	return sorted(albums, key=lambda album: album.day, reverse=True)[:count]


class EventPhotosProvider(Provider):
	name = "event_photos"

	def __init__(self, settings: dict, cache_folder: Path, default_seconds: float) -> None:
		self.settings = settings
		self.cache_folder = cache_folder
		self.albums_folder = settings.get("albums_folder", "images/albums").strip("/") + "/"
		self.recent_events = settings.get("recent_events", 3)
		self.photos_to_download = settings.get("photos_to_download", 15)
		self.photos_per_round = settings.get("photos_per_round", 1)
		self.seconds = settings.get("seconds", default_seconds)
		self.refresh_seconds = settings.get("refresh_minutes", 60) * 60
		self.photos: list[Photo] = []
		self.client: Nextcloud | None = None

	def connect(self) -> Nextcloud:
		if self.client is None:
			username, password = load_credentials(project_path(self.settings["credentials"]))
			self.client = Nextcloud(self.settings["server"], username, password)
		return self.client

	def refresh(self, now: datetime) -> None:
		client = self.connect()
		years = sorted((e for e in client.list_folder(self.albums_folder) if e.is_folder), key=lambda e: e.name, reverse=True)
		album_entries = [entry for year in years[:2] for entry in client.list_folder(year.path)]
		albums = most_recent_albums(album_entries, now.date(), self.recent_events)
		candidates = [
			(album, entry)
			for album in albums
			for entry in client.list_folder(album.path)
			if not entry.is_folder and Path(entry.name).suffix.lower() in IMAGE_EXTENSIONS
		]
		chosen = random.sample(candidates, min(self.photos_to_download, len(candidates)))

		self.cache_folder.mkdir(parents=True, exist_ok=True)
		photos = []
		for album, entry in chosen:
			local = self.cache_folder / f"{album.day}-{entry.name}"
			if not local.exists():
				client.download(entry.path, local)
			photos.append(Photo(local, album, is_portrait(local)))
		# Keep the previous batch too: the current round of the slideshow may still show one of them.
		keep = {photo.path for photo in photos} | {photo.path for photo in self.photos}
		for old in self.cache_folder.iterdir():
			if old not in keep:
				old.unlink()
		self.photos = photos
		log.info("Event photos from: %s", ", ".join(album.title for album in albums))

	def slides(self, now: datetime) -> list[Slide]:
		photos = [photo for photo in self.photos if photo.path.exists()]
		slides = []
		for photo in random.sample(photos, min(self.photos_per_round, len(photos))):
			shown = [photo]
			if photo.portrait:
				# A portrait photo alone leaves half the screen black: pair it with another one from
				# the same event, preferably also a portrait.
				others = [p for p in photos if p.album == photo.album and p is not photo]
				portraits = [p for p in others if p.portrait]
				if portraits or others:
					shown.append(random.choice(portraits or others))
			slides.append(Slide("photo.html", self.seconds, {
				"urls": [media_url(p.path) for p in shown],
				"title": photo.album.title,
				"day": photo.album.day,
			}))
		return slides
