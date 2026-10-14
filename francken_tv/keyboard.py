"""Keyboard shortcuts in the terminal that runs the slideshow:

	Ctrl+M (or Enter)  read quotes aloud on/off
	Ctrl+R             reload config/devices.json and redraw the presence chart

Only active when the slideshow runs in a terminal (not under systemd).
"""

from __future__ import annotations

import logging
import os
import sys
import termios
import threading
import tty
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
	from .app import App

log = logging.getLogger(__name__)

CTRL_M = {"\r", "\n"}   # terminals send the same key for Ctrl+M and Enter
CTRL_R = "\x12"


def handle_key(app: App, key: str) -> None:
	if key in CTRL_M:
		app.toggle_quotes()
	elif key == CTRL_R:
		app.reload_devices()


def listen(app: App) -> Callable[[], None]:
	"""Start reading keys in the background. Returns a function that restores the terminal."""
	if not sys.stdin.isatty():
		return lambda: None
	fd = sys.stdin.fileno()
	original = termios.tcgetattr(fd)
	tty.setcbreak(fd)   # single key presses, no echo; Ctrl+C still works

	def read_keys() -> None:
		while True:
			try:
				data = os.read(fd, 1)
			except OSError:
				return
			if not data:
				return
			try:
				handle_key(app, data.decode(errors="ignore"))
			except Exception:
				log.exception("Keyboard shortcut failed")

	threading.Thread(target=read_keys, name="keyboard", daemon=True).start()
	print("Keys: Ctrl+M = read quotes aloud on/off, Ctrl+R = reload devices.json, Ctrl+C = stop", flush=True)
	return lambda: termios.tcsetattr(fd, termios.TCSADRAIN, original)
