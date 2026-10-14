"""Who is in the room: the daily activity chart, and greeting people when they arrive."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from pathlib import Path

from ..activity_chart import render_chart
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
	name = "presence"

	def __init__(self, settings: dict, store: PresenceStore, devices: DeviceList, chart_path: Path,
			nyan_cat_path: Path, default_seconds: float) -> None:
		self.store = store
		self.devices = devices
		self.chart_path = chart_path
		self.nyan_cat_path = nyan_cat_path
		self.starts_at = parse_time(settings.get("chart_starts_at", "08:00"))
		self.seconds = settings.get("seconds", default_seconds)
		self.refresh_seconds = settings.get("chart_refresh_minutes", 5) * 60
		self.chart_date: date | None = None

	def refresh(self, now: datetime) -> None:
		midnight = datetime.combine(now.date(), time())
		sightings = self.store.known_sightings(midnight, now)
		if render_chart(sightings, self.devices.by_mac(), now, self.chart_path, self.starts_at, self.nyan_cat_path):
			self.chart_date = now.date()

	def slides(self, now: datetime) -> list[Slide]:
		if self.chart_date != now.date() or not self.chart_path.exists():
			return []   # nobody seen yet today
		return [Slide("image.html", self.seconds, {"url": media_url(self.chart_path)})]


def greeting_day(now: datetime, day_starts_at: time) -> date:
	"""Greetings reset at `day_starts_at` (04:00), not at midnight, so late nights count as one day."""
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
