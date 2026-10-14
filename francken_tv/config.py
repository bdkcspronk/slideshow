"""Loading config/config.toml and turning its values into Python objects."""

from __future__ import annotations

try:
	import tomllib   # built into Python 3.11 and newer
except ModuleNotFoundError:   # Python 3.10 and older: pip install tomli
	import tomli as tomllib
from datetime import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_DIR / "config" / "config.toml"
DATA_DIR = PROJECT_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
	with open(path, "rb") as file:
		return tomllib.load(file)


def project_path(value: str) -> Path:
	"""Resolve a path from the config: absolute, ~/..., or relative to the project folder."""
	path = Path(value).expanduser()
	return path if path.is_absolute() else PROJECT_DIR / path


def parse_time(value: str) -> time:
	hour, minute = value.split(":")
	return time(int(hour), int(minute))


def parse_weekday(name: str) -> int:
	"""'friday' -> 4, matching datetime.weekday()."""
	return WEEKDAYS.index(name.lower())
