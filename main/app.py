from __future__ import annotations

import argparse
import signal
import sys

try:
	import tkinter as tk
except ModuleNotFoundError:
	raise SystemExit(
		"Tkinter is required. On Debian/Ubuntu, install it with: sudo apt install python3-tk"
	) from None

try:
	from PIL import ImageFile
except ImportError as error:
	raise SystemExit(
		"Pillow's ImageTk support is required. On Debian/Ubuntu, install it with: "
		"sudo apt install python3-pil.imagetk"
	) from error

from .config import PROJECT_DIR, VRIJMIBO_FILENAME
from .files import find_audio, find_images
from .processes import start_system_terminal
from .slideshow import Slideshow


ImageFile.LOAD_TRUNCATED_IMAGES = True


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Display a folder of images like a screensaver.")
	parser.add_argument("--seconds", type=float, default=8.0, help="Seconds per image (default: 8)")
	parser.add_argument("--shuffle", action="store_true", help="Show images in random order")
	return parser.parse_args()


def main() -> None:
	args = parse_args()
	folder = PROJECT_DIR / "slides"
	if not folder.is_dir():
		raise SystemExit(f"Not a folder: {folder}")
	if args.seconds <= 0:
		raise SystemExit("--seconds must be greater than zero")

	images = find_images(folder)
	audio = find_audio(PROJECT_DIR / "audio")
	vrijmibo_image = next((path for path in images if path.name.lower() == VRIJMIBO_FILENAME), None)
	if vrijmibo_image is not None:
		images.remove(vrijmibo_image)
	if not images and vrijmibo_image is None:
		raise SystemExit(f"No supported images found in {folder}")

	quote_image = PROJECT_DIR / "quotes" / "images" / "quote.png"
	if not quote_image.is_file():
		print(f"Quote image not found yet; it will be generated: {quote_image}", file=sys.stderr)

	try:
		system_process = start_system_terminal()
	except OSError as error:
		raise SystemExit(f"Could not open terminal for run_system.py: {error}") from error
	print("run_system.py started successfully.")

	root = tk.Tk()
	slideshow = Slideshow(root, images, folder, args.seconds, args.shuffle, quote_image, vrijmibo_image, audio, system_process)
	shutdown = lambda _signum, _frame: slideshow.close()
	signal.signal(signal.SIGINT, shutdown)
	signal.signal(signal.SIGTERM, shutdown)
	try:
		root.mainloop()
	finally:
		slideshow.close()


if __name__ == "__main__":
	main()