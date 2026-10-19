"""The images in media/slides/ (posters, announcements, ...)."""

from __future__ import annotations

import random
from datetime import datetime

from ..config import project_path
from ..media import animation_seconds, find_images
from ..slides import Provider, Slide, media_url


class ImagesProvider(Provider):
	name = "images"
	title = "Posters"

	def __init__(self, settings: dict, default_seconds: float) -> None:
		self.folder = project_path(settings.get("folder", "media/slides"))
		self.shuffle = settings.get("shuffle", False)
		self.seconds = settings.get("seconds", default_seconds)

	def slides(self, now: datetime) -> list[Slide]:
		# The folder is read again every round, so added and removed images show up by themselves.
		paths = find_images(self.folder)
		if self.shuffle:
			random.shuffle(paths)
		return [
			Slide("image.html", max(self.seconds, animation_seconds(path)), {"url": media_url(path), "backdrop": True})
			for path in paths
		]
