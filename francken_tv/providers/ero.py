"""The emergency response officers: their photos with their names, animated in.

Nothing to configure: every picture in media/ERO/ is an officer, and the file name is the name
(media/ERO/Alex.png -> "Alex"). Read again every round, so adding or removing a
picture shows up without a restart. Without pictures the slide is left out.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ..config import project_path
from ..slides import Provider, Slide, media_url

log = logging.getLogger(__name__)

EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def school_year(now: datetime) -> str:
	"""The academic year, which starts in September: "'26-'27" from September 2026 until August 2027."""
	start = now.year if now.month >= 9 else now.year - 1
	return f"'{start % 100:02d}-'{(start + 1) % 100:02d}"


class EroProvider(Provider):
	name = "ero"
	title = "Emergency response officers"
	nothing_to_show = "No pictures in media/ERO/"

	def __init__(self, settings: dict, default_seconds: float) -> None:
		self.folder = project_path(settings.get("folder", "media/ERO"))
		self.seconds = settings.get("seconds", default_seconds)

	def slides(self, now: datetime) -> list[Slide]:
		if not self.folder.is_dir():
			return []
		files = sorted((f for f in self.folder.iterdir() if f.suffix.lower() in EXTENSIONS),
			key=lambda f: f.stem.lower())
		if not files:
			return []
		officers = [{"name": f.stem.replace("_", " "), "photo": media_url(f)} for f in files]
		return [Slide("ero.html", self.seconds, {"officers": officers, "school_year": school_year(now)})]
