"""Who is in the room: the daily activity chart, and greeting people when they arrive."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pathlib import Path

from PIL import Image

from ..activity_chart import MarkerStyle, bar_look, chart_view, generate_bright_color, parse_style, time_in_room
from ..announcer import Announcer
from ..config import parse_time
from ..devices import DeviceList
from ..presence_store import PresenceStore
from ..slides import Job, Provider, Slide, media_url

log = logging.getLogger(__name__)

# Only greet people who were seen this recently, so a restart doesn't greet everyone
# who was here this morning.
GREET_WINDOW = timedelta(minutes=5)


class PresenceChartProvider(Provider):
	"""Today's activity chart, drawn by templates/slides/presence.html (see activity_chart.py)."""

	name = "presence"
	title = "Activity chart"
	nothing_to_show = "Nobody seen yet today"

	def __init__(self, settings: dict, store: PresenceStore, devices: DeviceList, nyan_cat_path: Path,
			default_seconds: float) -> None:
		self.store = store
		self.devices = devices
		self.seconds = settings.get("seconds", default_seconds)
		self.day_starts_at = parse_time(settings.get("day_starts_at", "04:00"))
		self.nyan_cat = None
		if nyan_cat_path.is_file():
			with Image.open(nyan_cat_path) as image:
				self.nyan_cat = {"url": media_url(nyan_cat_path), "aspect": round(image.width / image.height, 3)}

	def slides(self, now: datetime) -> list[Slide]:
		# The chart shows the whole day until day_starts_at (04:00), so a late night doesn't start over at midnight.
		day_start = datetime.combine(greeting_day(now, self.day_starts_at), self.day_starts_at)
		chart = chart_view(self.store.known_sightings(day_start, now), self.devices.by_mac(), now)
		if chart is None:
			return []   # nobody seen yet today
		return [Slide("presence.html", self.seconds, {**chart, "nyan_cat": self.nyan_cat})]


class LeaderboardProvider(Provider):
	"""Who spent the most time in the room this week (since Monday)."""

	name = "leaderboard"
	title = "Leaderboard"

	def __init__(self, settings: dict, store: PresenceStore, devices: DeviceList, default_seconds: float) -> None:
		self.store = store
		self.devices = devices
		self.top = settings.get("top", 10)
		self.seconds = settings.get("seconds", default_seconds)

	def slides(self, now: datetime) -> list[Slide]:
		monday = datetime.combine(now.date() - timedelta(days=now.weekday()), time())
		sightings = self.store.known_sightings(monday, now)
		totals = time_in_room(sightings)
		if not totals:
			return []
		mac_of = {s.name: s.mac for s in sightings}
		ranking = sorted(totals.items(), key=lambda item: item[1][0], reverse=True)[: self.top]
		longest = ranking[0][1][0].total_seconds() or 1
		rows = []
		for place, (name, (total, days)) in enumerate(ranking, start=1):
			device = self.devices.get(mac_of[name])
			style = parse_style(device.options) if device else MarkerStyle()
			style = replace(style, color=style.color or generate_bright_color(mac_of[name] or name),
				shape="rainbow" if style.shape == "nyan cat" else style.shape)   # the same bars as the chart, without pictures
			width = round(total.total_seconds() / longest * 100, 1)
			minutes = round(total.total_seconds() / 60)
			rows.append({
				**bar_look(style, width, seed=name),
				"place": place, "name": name, "days": len(days),
				"time": f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min",
				"width": width,
			})
		return [Slide("leaderboard.html", self.seconds, {"rows": rows})]


def greeting_day(now: datetime, day_starts_at: time) -> date:
	"""Greetings and the activity chart reset at `day_starts_at` (04:00), not at midnight, so late nights count as one day."""
	return (now - timedelta(hours=day_starts_at.hour, minutes=day_starts_at.minute)).date()


class Greeter(Job):
	"""Says "Welcome <name>!" the first time someone is seen each day."""

	name = "greeter"
	check_every = timedelta(seconds=5)

	def __init__(self, settings: dict, store: PresenceStore, devices: DeviceList, announcer: Announcer) -> None:
		self.store = store
		self.devices = devices
		self.announcer = announcer
		self.day_starts_at = parse_time(settings.get("day_starts_at", "04:00"))
		self.last_check: datetime | None = None

	def tick(self, now: datetime) -> None:
		if self.last_check is not None and now - self.last_check < self.check_every:
			return
		self.last_check = now
		day = greeting_day(now, self.day_starts_at)
		for sighting in self.store.known_sightings(now - GREET_WINDOW, now + timedelta(seconds=1)):
			if self.store.was_greeted(day, sighting.name):
				continue
			self.store.mark_greeted(day, sighting.name)
			device = self.devices.get(sighting.mac)
			spoken_name = device.phonetic if device else sighting.name
			greeting = (device.greeting if device else None) or "Welcome"
			self.announcer.greet(f"{greeting} {spoken_name}!")
