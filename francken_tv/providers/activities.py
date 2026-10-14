"""Upcoming activities, scraped from professorfrancken.nl/association/activities.

If the website's layout changes, only parse_activities() needs fixing.
Test it with: python -m unittest tests.test_activities
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

from ..slides import Provider, Slide

log = logging.getLogger(__name__)

# Activity links look like /association/activities/2026-10-14-i-gma
ACTIVITY_LINK = re.compile(r"/association/activities/(\d{4}-\d{2}-\d{2})-")
TIME = re.compile(r"\bat (\d{1,2}:\d{2})")


@dataclass
class Activity:
	day: date
	title: str
	time: str | None       # "17:00"
	when: str              # as written on the website, e.g. "27 - 30 November at 01:00"
	location: str | None


def parse_activities(html: str) -> list[Activity]:
	soup = BeautifulSoup(html, "html.parser")
	activities: dict[tuple, Activity] = {}
	for link in soup.find_all("a", href=ACTIVITY_LINK):
		title = link.find(class_="agenda-item__header")
		if title is None:
			continue   # e.g. links in the calendar widget
		day = date.fromisoformat(ACTIVITY_LINK.search(link["href"]).group(1))
		when, location = "", None
		for small in link.find_all("small"):
			if small.find(class_="fa-clock"):
				when = small.get_text(" ", strip=True)
			elif small.find(class_="fa-map-marker"):
				location = small.get_text(" ", strip=True) or None
		time_match = TIME.search(when)
		activity = Activity(day, title.get_text(" ", strip=True), time_match.group(1) if time_match else None, when, location)
		activities[(activity.day, activity.title)] = activity   # the page may list an activity twice
	return sorted(activities.values(), key=lambda a: (a.day, a.time or ""))


class ActivitiesProvider(Provider):
	name = "activities"

	def __init__(self, settings: dict, default_seconds: float) -> None:
		self.url = settings.get("url", "https://professorfrancken.nl/association/activities")
		self.max_events = settings.get("max_events", 10)
		self.seconds = settings.get("seconds", default_seconds)
		self.refresh_seconds = settings.get("refresh_minutes", 30) * 60
		self.activities: list[Activity] = []

	def refresh(self, now: datetime) -> None:
		response = requests.get(self.url, timeout=30)
		response.raise_for_status()
		activities = parse_activities(response.text)
		if not activities:
			raise ValueError(f"No activities found on {self.url}; did the website layout change?")
		self.activities = activities

	def slides(self, now: datetime) -> list[Slide]:
		upcoming = [activity for activity in self.activities if activity.day >= now.date()][: self.max_events]
		if not upcoming:
			return []
		return [Slide("activities.html", self.seconds, {"activities": upcoming, "today": now.date()})]
