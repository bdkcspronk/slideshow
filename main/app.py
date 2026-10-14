from __future__ import annotations

import argparse
import os
import select
import signal
import sys
import termios
import tty

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
from .activities import ACTIVITIES_IMAGE, sync_activity_slide
from .nextcloud import EVENTS_PATH, sync_recent_event_images
from .processes import start_system_terminal
from .slideshow import Slideshow


ImageFile.LOAD_TRUNCATED_IMAGES = True


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Display a folder of images like a screensaver.")
	parser.add_argument("--seconds", type=float, default=8.0, help="Seconds per image (default: 8)")
	parser.add_argument("--shuffle", action="store_true", help="Show images in random order")
	parser.add_argument("--nextcloud", action="store_true", help="Include images from the three newest Nextcloud events")
	return parser.parse_args()


def main() -> None:
	args = parse_args()
	folder = PROJECT_DIR / "slides"
	if not folder.is_dir():
		raise SystemExit(f"Not a folder: {folder}")
	if args.seconds <= 0:
		raise SystemExit("--seconds must be greater than zero")

	activity_image = None
	try:
		activity_image = sync_activity_slide()
	except RuntimeError as error:
		print(f"Could not update activities slide: {error}", file=sys.stderr)
		if ACTIVITIES_IMAGE.is_file():
			activity_image = ACTIVITIES_IMAGE
	images = [path for path in find_images(folder) if not path.name.startswith("eventpicture_")]
	nextcloud_images = None
	EVENTS_PATH.mkdir(parents=True, exist_ok=True)
	audio = find_audio(PROJECT_DIR / "audio")
	vrijmibo_image = next((path for path in images if path.name.lower() == VRIJMIBO_FILENAME), None)
	if vrijmibo_image is not None:
		images.remove(vrijmibo_image)
	if not images and vrijmibo_image is None and not args.nextcloud:
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
	slideshow = Slideshow(
		root, images, folder, args.seconds, args.shuffle or args.nextcloud,
		quote_image, vrijmibo_image, audio, system_process, nextcloud_images,
		sync_recent_event_images, activity_image, sync_activity_slide,
	)
	terminal_attributes = None
	if sys.stdin.isatty():
		terminal_attributes = termios.tcgetattr(sys.stdin)
		tty.setcbreak(sys.stdin.fileno())

	def poll_terminal_toggle() -> None:
		try:
			readable, _, _ = select.select([sys.stdin], [], [], 0)
			if readable:
				key = sys.stdin.read(1)
				if key in ("\r", "\n"):
					slideshow.toggle_quote_voice()
				elif key == "\x12":
					try:
						if slideshow.system_process is not None and slideshow.system_process.poll() is None:
							os.kill(slideshow.system_process.pid, signal.SIGUSR1)
							print("Requested filter.json reload in the sniffer.", flush=True)
					except OSError as error:
						print(f"Could not request sniffer reload: {error}", file=sys.stderr)
		except (OSError, ValueError):
			return
		root.after(100, poll_terminal_toggle)
	poll_terminal_toggle()
	shutdown = lambda _signum, _frame: slideshow.close()
	signal.signal(signal.SIGINT, shutdown)
	signal.signal(signal.SIGTERM, shutdown)
	try:
		root.mainloop()
	finally:
		if terminal_attributes is not None:
			termios.tcsetattr(sys.stdin, termios.TCSADRAIN, terminal_attributes)
		slideshow.close()


if __name__ == "__main__":
	main()