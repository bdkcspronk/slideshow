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
   is in the order. take_turns can also be a list of such groups (e.g. presence and leaderboard).
4. The menu's "Rotation settings of slides" (rotation.py) can change all of this on the TV: per slide type and per group
   how often (every 5th round, once an hour, ...), in which months, on which days and at what time of day, and which
   slide types take turns. A slide type outside its hours still gets its outside_daytime_slides() (the rain warning).
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import replace
from datetime import datetime, time

from .rotation import Group, Rule
from .slides import Provider, Slide, Takeover

log = logging.getLogger(__name__)

EMPTY_SLIDE = Slide(template="empty.html", seconds=10)


class Scheduler:
	def __init__(self, providers: list[Provider], takeovers: list[Takeover], fill_with: str = "images",
			daytime_only: set[str] | None = None, daytime: tuple[time, time] = (time(8, 0), time(16, 0)),
			take_turns: list | None = None) -> None:
		self.providers = providers
		self.fill_with = fill_with
		self.daytime_only = daytime_only or set()   # e.g. the news and books slides: not in the evening and night
		self.daytime = daytime                      # (from, until), e.g. 08:00 until bieruur
		# Of each group one per round, the next one each round. In the order of rotation.order, as config.toml lists them.
		order = [provider.name for provider in providers]
		self.config_groups = [Group(tuple(sorted(group, key=lambda name: order.index(name) if name in order else len(order))))
			for group in turn_groups(take_turns)]
		self.groups = self.config_groups
		self.turns: dict[str, int] = {}             # group key -> the member whose turn is next
		self.rules: dict[str, Rule] = {}            # slide type -> its rule, from the menu; the others: default_rule()
		self.last: dict[str, tuple[int, datetime]] = {}   # slide type or group key -> (round, time) it was last shown
		self.round_number = 0
		self.takeovers = takeovers
		self.round: deque[Slide] = deque()
		self.speed = 1.0                 # 2 = every slide is shown half as long and plays twice as fast (the menu's Settings)
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
			if self.speed != 1.0 and not slide.real_time:
				# Shorter (or longer), and played that much faster (slower), so what happens on it still fills its time:
				# the player runs the slide's animations at this rate (setRate() in static/player.js).
				# What can't be played faster (a GIF) keeps the time it needs (min_seconds), and the rate follows the time it gets.
				seconds = max(slide.seconds / self.speed, min(slide.min_seconds, slide.seconds))
				slide = replace(slide, seconds=seconds, rate=slide.seconds / seconds)
			return self.cut_short_before_takeover(slide, now)

	def hide(self, names: set[str]) -> None:
		"""Leave these slide types out, starting with a new round right away."""
		with self.lock:
			if names != self.hidden:
				self.hidden = set(names)
				self.round.clear()

	def set_rotation(self, rules: dict[str, Rule], groups: list[Group] | None) -> None:
		"""The rules and groups from the menu (None: the groups of config.toml), starting with a new round right away."""
		with self.lock:
			groups = self.config_groups if groups is None else groups
			if rules != self.rules or groups != self.groups:
				self.rules, self.groups = dict(rules), list(groups)
				self.round.clear()

	def rule(self, name: str) -> Rule:
		return self.rules.get(name) or (Rule(hours="daytime") if name in self.daytime_only else Rule())

	def build_round(self, now: datetime) -> list[Slide]:
		self.round_number += 1
		filler: list[Slide] = []
		special: list[Slide] = []
		shown = [provider for provider in self.providers if provider.name not in self.hidden]
		groups = [(group, [provider for provider in shown if provider.name in group.slides])
			for group in self.groups if group.on]
		grouped = {name for group in self.groups for name in group.slides}
		for provider in shown:
			group = next(((group, turns) for group, turns in groups if provider in turns), None)
			if group is None and provider.name in grouped:
				continue   # its group is switched off
			if group is not None and provider is not group[1][0]:
				continue   # the slide types taking turns share the place of the first of them
			slides = self.slides_of(provider, now) if group is None else self.next_turn(*group, now)
			(filler if provider.name == self.fill_with else special).extend(slides)
		return spread(filler, special)

	def next_turn(self, group: Group, turns: list[Provider], now: datetime) -> list[Slide]:
		"""The slides of the next of `turns` that has something to show, if the group's own rule lets it come round."""
		rule = group.rule
		if not (rule.on_this_day(now) and rule.in_hours(now, self.daytime) and rule.due(self.last.get(group.key), self.round_number, now)):
			return []
		start = self.turns.get(group.key, 0)
		for step in range(len(turns)):
			index = (start + step) % len(turns)
			slides = self.slides_of(turns[index], now)
			if slides:
				self.turns[group.key] = index + 1
				self.last[group.key] = (self.round_number, now)
				return slides
		return []

	def slides_of(self, provider: Provider, now: datetime) -> list[Slide]:
		"""The provider's slides for this round, if its rule lets it come round; outside its hours the ones it shows then."""
		rule = self.rule(provider.name)
		if not (rule.on_this_day(now) and rule.due(self.last.get(provider.name), self.round_number, now)):
			return []
		try:
			slides = provider.slides(now) if rule.in_hours(now, self.daytime) else provider.outside_daytime_slides(now)
		except Exception:
			log.exception("Provider %s failed; skipping it this round", provider.name)
			return []
		if slides:
			self.last[provider.name] = (self.round_number, now)
		return slides

	def cut_short_before_takeover(self, slide: Slide, now: datetime) -> Slide:
		"""Shorten a slide so that an upcoming takeover starts on time."""
		starts = [start for takeover in self.takeovers if (start := takeover.next_start(now))]
		if not starts:
			return slide
		seconds_left = (min(starts) - now).total_seconds()
		if 0 < seconds_left < slide.seconds:
			return replace(slide, seconds=max(1.0, seconds_left), cut_short=True)
		return slide


def turn_groups(take_turns: list | None) -> list[set[str]]:
	"""A flat list of names is one group; a list of lists is several."""
	if not take_turns:
		return []
	if all(isinstance(item, str) for item in take_turns):
		return [set(take_turns)]
	return [set(group) for group in take_turns]


def spread(filler: list[Slide], special: list[Slide]) -> list[Slide]:
	"""Spread the special slides evenly between the filler slides.

	26 posters and 6 special slides: a special slide after about every 4 posters,
	the last one at the end of the round.
	"""
	# Special slide k goes after filler slide number ceil((k + 1) * len(filler) / len(special)).
	places = [(i + 1, 0, i) for i in range(len(filler))]
	places += [(-(-(k + 1) * len(filler) // len(special)), 1, k) for k in range(len(special))]
	return [(filler, special)[kind][index] for _, kind, index in sorted(places)]
