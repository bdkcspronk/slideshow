"""Helpers for image files."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}


def find_images(folder: Path) -> list[Path]:
	if not folder.is_dir():
		return []
	return sorted(
		path for path in folder.iterdir()
		if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
	)


def animation_seconds(path: Path) -> float:
	"""How long one loop of an animated GIF takes in a browser (0 for still images)."""
	stat = path.stat()
	return _animation_seconds(path, stat.st_mtime, stat.st_size)


@lru_cache(maxsize=64)
def _animation_seconds(path: Path, _mtime: float, _size: int) -> float:
	with Image.open(path) as image:
		frames = getattr(image, "n_frames", 1)
		if frames <= 1:
			return 0.0
		total_ms = 0
		for index in range(frames):
			image.seek(index)
			duration = image.info.get("duration", 100)
			# Browsers play frames shorter than 20 ms at 100 ms.
			total_ms += duration if duration >= 20 else 100
	return total_ms / 1000
