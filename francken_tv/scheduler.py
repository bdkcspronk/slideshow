"""Decides which slide comes next.

1. If a takeover wants the screen (bieruur, vrijmibo), it gets it.
2. Otherwise the next slide of the current round is shown. A round is built by asking
   every provider in `rotation.order` for its slides; the slides of the other providers
   are spread evenly between the "filler" slides (the posters in media/slides/).
   Slide types in `rotation.daytime_only` (news, books, ...) are left out of rounds outside the daytime
   (from rotation.daytime_from until bieruur), except for their outside_daytime_slides() (the weather
   when it's going to rain).
3. Slide types in `rotation.take_turns` (the info slides: news, weather, buses, timetable) share one
   place in the round: each round the next of them that has something to show, where the first of them
   is in the order.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import replace
from datetime import datetime, time

from .slides import Provider, Slide, Takeover

log = logging.getLogger(__name__)

EMPTY_SLIDE = Slide(template="empty.html", seconds=10)


class Scheduler:
	def __init__(self, providers: list[Provider], takeovers: list[Takeover], fill_with: str = "images",
			daytime_only: set[str] | None = None, daytime: tuple[time, time] = (time(8, 0), time(16, 0)),
			take_turns: list[str] | None = None) -> None:
		self.providers = providers
		self.fill_with = fill_with
		self.daytime_only = daytime_only or set()   # e.g. the news and books slides: not in the evening and night
		self.daytime = daytime                      # (from, until), e.g. 08:00 until bieruur
		self.take_turns = set(take_turns or [])     # one of these per round, the next one each round
		self.turn = 0
		self.takeovers = takeovers
		self.round: deque[Slide] = deque()
		self.speed = 1.0                 # 2 = every slide is shown half as long (the menu's Settings)
		self.hidden: set[str] = set()    # slide types left out of the rounds (the menu's Settings)
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
			if self.speed != 1.0:
				slide = replace(slide, seconds=slide.seconds / self.speed)
			return self.cut_short_before_takeover(slide, now)

	def hide(self, names: set[str]) -> None:
		"""Leave these slide types out, starting with a new round right away."""
		with self.lock:
			if names != self.hidden:
				self.hidden = set(names)
				self.round.clear()

	def build_round(self, now: datetime) -> list[Slide]:
		filler: list[Slide] = []
		special: list[Slide] = []
		daytime = self.daytime[0] <= now.time() < self.daytime[1]
		shown = [provider for provider in self.providers if provider.name not in self.hidden]
		turns = [provider for provider in shown if provider.name in self.take_turns]
		for provider in shown:
			if provider in turns[1:]:
				continue   # the slide types taking turns share the place of the first of them
			slides = self.next_turn(turns, now, daytime) if provider in turns else self.slides_of(provider, now, daytime)
			(filler if provider.name == self.fill_with else special).extend(slides)
		return spread(filler, special)

	def next_turn(self, turns: list[Provider], now: datetime, daytime: bool) -> list[Slide]:
		"""The slides of the next of `turns` that has something to show."""
		for step in range(len(turns)):
			index = (self.turn + step) % len(turns)
			slides = self.slides_of(turns[index], now, daytime)
			if slides:
				self.turn = index + 1
				return slides
		return []

	def slides_of(self, provider: Provider, now: datetime, daytime: bool) -> list[Slide]:
		try:
			if provider.name in self.daytime_only and not daytime:
				return provider.outside_daytime_slides(now)
			return provider.slides(now)
		except Exception:
			log.exception("Provider %s failed; skipping it this round", provider.name)
			return []

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
	# Special slide k goes after filler slide number ceil((k + 1) * len(filler) / len(special)).
	places = [(i + 1, 0, i) for i in range(len(filler))]
	places += [(-(-(k + 1) * len(filler) // len(special)), 1, k) for k in range(len(special))]
	return [(filler, special)[kind][index] for _, kind, index in sorted(places)]
