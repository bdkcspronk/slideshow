"""The confidential contact persons: their photos, names and email addresses, animated in.

Personal data, so not in git (the repository is public): who they are is in config/confidential.json,
their photos in media/confidential/. Both go to the TV PC by hand, like config/devices.json. Read
again every round, so changes show up without a restart. The file:

	{
		"title": "Confidential contact persons",
		"intro": "Feel free to come up to us or reach out via our email:",
		"email": "the shared address",
		"website": "https://www.professorfrancken.nl/association/mental-health",
		"people": [{"name": "...", "email": "...", "photo": "media/confidential/....jpg"}, ...]
	}
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from ..config import project_path
from ..slides import Provider, Slide, media_url

log = logging.getLogger(__name__)


def email_parts(email: str) -> list[str]:
	"""Where a long address may break: after a dot before the @, and before the @ (the domain stays
	whole): "alex.example.person@example.com" -> ["alex.", "example.", "person", "@example.com"]."""
	local, at, domain = email.partition("@")
	return [part for part in re.split(r"(?<=\.)", local) if part] + ([at + domain] if at else [])


class ConfidentialProvider(Provider):
	name = "confidential"
	title = "Confidential contact persons"
	nothing_to_show = "No confidential contact persons in config/confidential.json"

	def __init__(self, settings: dict, default_seconds: float) -> None:
		self.path = project_path(settings.get("file", "config/confidential.json"))
		self.seconds = settings.get("seconds", default_seconds)

	def load(self) -> dict | None:
		if not self.path.exists():
			return None
		try:
			data = json.loads(self.path.read_text(encoding="utf-8"))
		except (OSError, ValueError) as error:
			log.warning("Ignoring unreadable %s: %s", self.path, error)
			return None
		return data if data.get("people") else None

	def slides(self, now: datetime) -> list[Slide]:
		data = self.load()
		if data is None:
			return []
		people = []
		for person in data["people"]:
			photo = project_path(person["photo"]) if person.get("photo") else None
			email = person.get("email", "")
			people.append({"name": person.get("name", ""), "email": email,
				"email_parts": email_parts(email),
				"photo": media_url(photo) if photo and photo.exists() else None})
		return [Slide("confidential.html", self.seconds, {
			"title": data.get("title", "Confidential contact persons"),
			"intro": data.get("intro", "Feel free to come up to us or reach out via our email:"),
			"email": data.get("email", ""),
			"website": data.get("website", ""),
			"people": people,
		})]
