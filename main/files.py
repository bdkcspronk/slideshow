from pathlib import Path

from .config import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS


def find_images(folder: Path) -> list[Path]:
	return sorted(
		path for path in folder.iterdir()
		if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
	)


def find_audio(folder: Path) -> list[Path]:
	return sorted(
		path for path in folder.iterdir()
		if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
	)