"""The one place that knows the current time.

Everything else receives `now` as an argument, so you can test or preview the
slideshow at any moment, e.g. `python -m francken_tv --fake-time "2026-10-16 15:57"`.
"""

from __future__ import annotations

from datetime import datetime, timedelta


class Clock:
	def __init__(self, fake_start: datetime | None = None) -> None:
		self.offset = fake_start - datetime.now() if fake_start else timedelta(0)

	def now(self) -> datetime:
		return datetime.now() + self.offset
