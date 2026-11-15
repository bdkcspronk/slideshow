"""Settings changed on the TV itself (Esc -> Settings), saved in data/settings.json so they survive
a restart. config.toml gives the values to start with; once something is changed on the TV, the
saved value wins. Delete data/settings.json to go back to config.toml.

The rotation (Esc -> Settings -> Rotation settings of slides: ROTATION_FIELDS) is saved in config/rotation.json
instead, which is in git: the TV commits and pushes it (updater.py), so every PC running the slideshow follows it.
"Reset to default" on that page empties it.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

from .rotation import clean_groups, clean_rules

log = logging.getLogger(__name__)

SPEEDS = [0.5, 0.75, 1.0, 1.5, 2.0]   # the choices in the menu; 2 = slides change twice as fast
ROTATION_FIELDS = ("hidden", "rules", "groups")   # saved in config/rotation.json, shared through git


@dataclass
class Settings:
	muted: bool = False          # no sound at all from the TV PC, Spotify too (system_volume.py)
	quotes_aloud: bool = False   # read the quotes aloud
	greetings: bool = True       # greet people who walk in
	volume: int = 100            # 0-100, the TV PC's main volume, Spotify too (system_volume.py)
	speed: float = 1.0           # see SPEEDS
	hidden: list[str] = field(default_factory=list)   # slide types left out of the rotation
	permanent_pause: bool = False   # space pauses until it's pressed again; otherwise the slideshow goes on after 4 minutes
	rules: dict = field(default_factory=dict)   # slide type -> when and how often it comes round (rotation.py); none: the default
	groups: list | None = None      # the slide types that take turns (rotation.py); None: rotation.take_turns in config.toml

	def changed(self, changes: dict) -> Settings:
		"""A copy with `changes` (from the menu) applied; unknown names and wrong types raise ValueError."""
		known = {f.name: f for f in fields(self)}
		clean = {}
		for name, value in changes.items():
			if name not in known:
				raise ValueError(f"unknown setting {name!r}")
			if name in ("muted", "quotes_aloud", "greetings", "permanent_pause"):
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
			elif name == "rules":
				value = clean_rules(value)
			elif name == "groups":
				value = clean_groups(value)
			clean[name] = value
		return replace(self, **clean)


def load_settings(path: Path, defaults: Settings, rotation_path: Path | None = None) -> Settings:
	"""The saved settings on top of `defaults` (from config.toml), and the rotation file on top of those."""
	settings = defaults
	for file in (path, rotation_path):
		if file is None or not file.exists():
			continue
		try:
			saved = json.loads(file.read_text(encoding="utf-8"))
			settings = settings.changed(saved)
		except (OSError, ValueError, AttributeError, TypeError) as error:
			log.warning("Ignoring unreadable settings %s: %s", file, error)
	return settings


def save_settings(path: Path, settings: Settings, rotation_path: Path | None = None) -> bool:
	"""Save the settings. With a rotation_path, the rotation (ROTATION_FIELDS) goes there instead of into `path`, and
	this returns whether that file changed (then it's to be shared through git: updater.py, share_soon())."""
	values = asdict(settings)
	if rotation_path is None:
		write(path, json.dumps(values, indent=2))
		return False
	write(path, json.dumps({name: value for name, value in values.items() if name not in ROTATION_FIELDS}, indent=2))
	rotation = json.dumps({name: values[name] for name in ROTATION_FIELDS}, indent=2, sort_keys=True) + "\n"
	try:
		if rotation_path.read_text(encoding="utf-8") == rotation:
			return False
	except OSError:
		pass   # not there yet
	write(rotation_path, rotation)
	return True


def write(path: Path, text: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	temporary = path.with_suffix(f".{threading.get_ident()}.tmp")
	temporary.write_text(text, encoding="utf-8")
	temporary.replace(path)   # in one go, so a restart while saving can't leave half a file
