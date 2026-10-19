"""Keyboard shortcuts in the terminal that runs the slideshow:

	Ctrl+M (or Enter)  read quotes aloud on/off
	Ctrl+R             restart the slideshow (e.g. after a git pull or a change in config.toml)

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


def handle_key(app: App, key: str, restart: Callable[[], None]) -> None:
	if key in CTRL_M:
		app.toggle_quotes()
	elif key == CTRL_R:
		restart()


def listen(app: App, restart: Callable[[], None]) -> Callable[[], None]:
	"""Start reading keys in the background. Returns a function that restores the terminal.
	`restart` is called for Ctrl+R (see __main__.py)."""
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
				handle_key(app, data.decode(errors="ignore"), restart)
			except Exception:
				log.exception("Keyboard shortcut failed")

	threading.Thread(target=read_keys, name="keyboard", daemon=True).start()
	print("Keys: Ctrl+M = read quotes aloud on/off, Ctrl+R = restart the slideshow, Ctrl+C = stop", flush=True)
	return lambda: termios.tcsetattr(fd, termios.TCSADRAIN, original)
