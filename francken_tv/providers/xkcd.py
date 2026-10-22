"""The latest xkcd comic (xkcd.com), with its title and the hover text (the alt text: often the best joke).

xkcd has a small JSON feed of the latest comic (info.0.json). The image is downloaded once per comic
into data/cache/xkcd, in double size when xkcd has it (sharper on the TV).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import requests

from ..slides import Provider, Slide, media_url

log = logging.getLogger(__name__)

LATEST_URL = "https://xkcd.com/info.0.json"


@dataclass
class Comic:
	number: int
	title: str
	alt: str
	day: date
	image: str   # the downloaded copy, as a /files/ url


class XkcdProvider(Provider):
	name = "xkcd"
	title = "xkcd"
	nothing_to_show = "The latest xkcd couldn't be downloaded"

	def __init__(self, settings: dict, cache_folder: Path, default_seconds: float) -> None:
		self.cache_folder = cache_folder
		self.seconds = settings.get("seconds", default_seconds)
		self.refresh_seconds = settings.get("refresh_minutes", 60) * 60
		self.comic: Comic | None = None

	def refresh(self, now: datetime) -> None:
		response = requests.get(LATEST_URL, timeout=20)
		response.raise_for_status()
		data = response.json()
		number = int(data["num"])
		if self.comic and self.comic.number == number:
			return   # still the same comic
		self.cache_folder.mkdir(parents=True, exist_ok=True)
		path = self.cache_folder / f"{number}.png"
		if not path.exists():
			path.write_bytes(self.download_image(data["img"]))
		for old in self.cache_folder.iterdir():
			if old != path:
				old.unlink()
		self.comic = Comic(number, data.get("safe_title") or data["title"], data.get("alt", ""),
			date(int(data["year"]), int(data["month"]), int(data["day"])), media_url(path))
		log.info("Latest xkcd: #%d %s", number, self.comic.title)

	@staticmethod
	def download_image(url: str) -> bytes:
		"""The double-size version (name_2x.png) if xkcd has one, else the normal one."""
		for candidate in ([url.replace(".png", "_2x.png")] if url.endswith(".png") else []) + [url]:
			response = requests.get(candidate, timeout=30)
			if response.ok and response.content:
				return response.content
		response.raise_for_status()
		raise ValueError(f"no image at {url}")

	def slides(self, now: datetime) -> list[Slide]:
		if self.comic is None:
			return []
		return [Slide("xkcd.html", self.seconds, {"comic": self.comic, "today": now.date()})]
