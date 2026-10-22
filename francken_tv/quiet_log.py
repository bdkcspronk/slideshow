"""Keeps the terminal readable when something is down for a while (no internet, a website offline).

The slideshow tries again every minute, and every try would log the same warning again. This filter
lets a warning or error through once and then drops the same message (same logger, same text) for an
hour; /status still shows the latest error of each slide type.
"""

from __future__ import annotations

import logging
import time

REPEAT_AFTER_SECONDS = 3600


class OncePerHour(logging.Filter):
	def __init__(self) -> None:
		super().__init__()
		self.seen: dict[tuple[str, str], float] = {}   # (logger, message) -> when it was last let through

	def filter(self, record: logging.LogRecord) -> bool:
		if record.levelno < logging.WARNING:
			return True
		key = (record.name, record.getMessage())
		now = time.monotonic()
		if now - self.seen.get(key, -REPEAT_AFTER_SECONDS) < REPEAT_AFTER_SECONDS:
			return False
		self.seen[key] = now
		if len(self.seen) > 1000:   # don't grow forever
			self.seen = {k: t for k, t in self.seen.items() if now - t < REPEAT_AFTER_SECONDS}
		return True


def install() -> None:
	"""On the handlers of the root logger (set up by logging.basicConfig in __main__.py)."""
	quiet = OncePerHour()
	for handler in logging.getLogger().handlers:
		handler.addFilter(quiet)
