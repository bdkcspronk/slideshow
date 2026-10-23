"""The extern: "Internship? Job? Thesis?" in turn, then their photo, name and phone number, animated in.

Personal data, so not in git (the repository is public): the text is in config/extern.json, the photo
and the background in media/extern/. Both go to the TV PC by hand, like config/confidential.json. Read
again every round, so changes show up without a restart. The file:

	{
		"questions": ["Internship?", "Job?", "Thesis?"],
		"ask": "Ask our extern - Name",
		"contacts": [{"label": "Phone", "value": "+31 6 ...", "note": "(also WhatsApp)"},
			{"label": "Email", "value": "extern@professorfrancken.nl"}],
		"photo": "media/extern/name.png",
		"background": "media/extern/background.png"
	}

The photo may be a PNG with a transparent shape around it; it's shown as is.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from ..config import project_path
from ..slides import Provider, Slide, media_url

log = logging.getLogger(__name__)


class ExternProvider(Provider):
	name = "extern"
	title = "Our extern"
	nothing_to_show = "No extern in config/extern.json"

	def __init__(self, settings: dict, default_seconds: float) -> None:
		self.path = project_path(settings.get("file", "config/extern.json"))
		self.seconds = settings.get("seconds", default_seconds)

	def load(self) -> dict | None:
		if not self.path.exists():
			return None
		try:
			return json.loads(self.path.read_text(encoding="utf-8"))
		except (OSError, ValueError) as error:
			log.warning("Ignoring unreadable %s: %s", self.path, error)
			return None

	def slides(self, now: datetime) -> list[Slide]:
		data = self.load()
		if data is None:
			return []
		files = {key: project_path(data[key]) for key in ("photo", "background") if data.get(key)}
		return [Slide("extern.html", self.seconds, {
			"questions": data.get("questions", ["Internship?", "Job?", "Thesis?"]),
			"ask": data.get("ask", ""),
			"contacts": data.get("contacts", []),
			**{key: media_url(path) if path.exists() else None for key, path in files.items()},
		})]
