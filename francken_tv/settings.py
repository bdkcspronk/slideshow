"""Settings changed on the TV itself (Esc -> Settings), saved in data/settings.json so they survive
a restart. config.toml gives the values to start with; once something is changed on the TV, the
saved value wins. Delete data/settings.json to go back to config.toml.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

log = logging.getLogger(__name__)

SPEEDS = [0.5, 0.75, 1.0, 1.5, 2.0]   # the choices in the menu; 2 = slides change twice as fast


@dataclass
class Settings:
	muted: bool = False          # no sound at all from the TV PC, Spotify too (system_volume.py)
	quotes_aloud: bool = False   # read the quotes aloud
	greetings: bool = True       # greet people who walk in
	volume: int = 100            # 0-100, the TV PC's main volume, Spotify too (system_volume.py)
	speed: float = 1.0           # see SPEEDS
	hidden: list[str] = field(default_factory=list)   # slide types left out of the rotation

	def changed(self, changes: dict) -> Settings:
		"""A copy with `changes` (from the menu) applied; unknown names and wrong types raise ValueError."""
		known = {f.name: f for f in fields(self)}
		clean = {}
		for name, value in changes.items():
			if name not in known:
				raise ValueError(f"unknown setting {name!r}")
			if name in ("muted", "quotes_aloud", "greetings"):
				if not isinstance(value, bool):
					raise ValueError(f"{name} must be true or false")
			elif name == "volume":
				if not isinstance(value, (int, float)) or isinstance(value, bool):
					raise ValueError("volume must be a number")
				value = max(0, min(100, round(value)))
			elif name == "speed":
				if value not in SPEEDS:
					raise ValueError(f"speed must be one of {SPEEDS}")
				value = float(value)
			elif name == "hidden":
				if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
					raise ValueError("hidden must be a list of slide types")
			clean[name] = value
		return replace(self, **clean)


def load_settings(path: Path, defaults: Settings) -> Settings:
	"""The saved settings on top of `defaults` (from config.toml)."""
	if not path.exists():
		return defaults
	try:
		saved = json.loads(path.read_text(encoding="utf-8"))
		return defaults.changed(saved)
	except (OSError, ValueError, AttributeError) as error:
		log.warning("Ignoring unreadable settings %s: %s", path, error)
		return defaults


def save_settings(path: Path, settings: Settings) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	temporary = path.with_suffix(f".{threading.get_ident()}.tmp")
	temporary.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
	temporary.replace(path)   # in one go, so a restart while saving can't leave half a file
