"""Decides which slide comes next.

1. If a takeover wants the screen (bieruur, vrijmibo), it gets it.
2. Otherwise the next slide of the current round is shown. A round is built by asking
   every provider in `rotation.order` for its slides; the slides of the other providers
   are spread evenly between the "filler" slides (the posters in media/slides/).
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import replace
from datetime import datetime

from .slides import Provider, Slide, Takeover

log = logging.getLogger(__name__)

EMPTY_SLIDE = Slide(template="empty.html", seconds=10)


class Scheduler:
	def __init__(self, providers: list[Provider], takeovers: list[Takeover], fill_with: str = "images") -> None:
		self.providers = providers
		self.fill_with = fill_with
		self.takeovers = takeovers
		self.round: deque[Slide] = deque()
		self.lock = threading.Lock()

	def next_slide(self, now: datetime) -> Slide:
		with self.lock:
			for takeover in self.takeovers:
				try:
					slide = takeover.slide(now)
				except Exception:
					log.exception("Takeover %s failed", takeover.name)
					continue
				if slide is not None:
					return self.cut_short_before_takeover(slide, now)

			if not self.round:
				self.round.extend(self.build_round(now))
			slide = self.round.popleft() if self.round else EMPTY_SLIDE
			return self.cut_short_before_takeover(slide, now)

	def build_round(self, now: datetime) -> list[Slide]:
		filler: list[Slide] = []
		special: list[Slide] = []
		for provider in self.providers:
			try:
				slides = provider.slides(now)
			except Exception:
				log.exception("Provider %s failed; skipping it this round", provider.name)
				continue
			(filler if provider.name == self.fill_with else special).extend(slides)
		return spread(filler, special)

	def cut_short_before_takeover(self, slide: Slide, now: datetime) -> Slide:
		"""Shorten a slide so that an upcoming takeover starts on time."""
		starts = [start for takeover in self.takeovers if (start := takeover.next_start(now))]
		if not starts:
			return slide
		seconds_left = (min(starts) - now).total_seconds()
		if 0 < seconds_left < slide.seconds:
			return replace(slide, seconds=max(1.0, seconds_left))
		return slide


def spread(filler: list[Slide], special: list[Slide]) -> list[Slide]:
	"""Spread the special slides evenly between the filler slides.

	26 posters and 6 special slides: a special slide after about every 4 posters,
	the last one at the end of the round.
	"""
	if not filler or not special:
		return filler + special
	result: list[Slide] = []
	placed = 0
	for index, slide in enumerate(filler, start=1):
		result.append(slide)
		# Place special slides until we're as far through them as through the filler.
		while placed < len(special) and (placed + 1) * len(filler) <= index * len(special):
			result.append(special[placed])
			placed += 1
	return result + special[placed:]
