"""Practice sessions in the next two weeks, from the activities on the website (providers/activities.py),
as a poster (templates/slides/practice.html): a big "Practice sessions" headline on the left, and a
ticket per session on the right with its date, course, time and room. The slide is only there while
there's at least one.

A session is an activity with "practice session" in its title; the rest of the title is the course.
The website has no room for them, so that's "Room TBA" unless the activity has a location. Today's
sessions are left out two hours after they start (SHOWN_AFTER_START).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from functools import lru_cache

from PIL import ImageFont

from ..config import PROJECT_DIR
from ..slides import Provider, Slide
from .activities import ActivitiesProvider

PRACTICE = re.compile(r"\s*practice\s+sessions?\s*", re.IGNORECASE)
DAYS_AHEAD = 14
SHOWN_AFTER_START = timedelta(hours=2)   # roughly how long a session takes
MAX_SESSIONS = 8
FONT = PROJECT_DIR / "francken_tv/static/vendor/familjen-grotesk/familjen-grotesk-700.woff"
# The tickets, in px on the 1920 x 1080 poster (see "Practice sessions" in style.css).
TICKETS_HEIGHT = 900     # the column they're stacked in
TICKET_WIDTH = 900
TICKET_GAP = 22
TICKET_MAX = 150         # height of one ticket when there are few


@lru_cache(maxsize=256)
def text_width(text: str) -> float:
	"""The width of the text in the poster's font at 100 px."""
	return ImageFont.truetype(str(FONT), 100).getlength(text)


def ticket_size(count: int) -> float:
	return min(TICKET_MAX, (TICKETS_HEIGHT - TICKET_GAP * (count - 1)) / count)


def course_size(course: str, height: float) -> float:
	"""The course name's font size: in proportion to the ticket, smaller when the name is long."""
	room = TICKET_WIDTH - date_width(height) - 2 * 36
	return round(min(height * 0.34, room / text_width(course) * 100), 1)


def date_width(height: float) -> float:
	return round(max(120, height * 1.1), 1)


class PracticeSessionsProvider(Provider):
	name = "practice"
	title = "Practice sessions"
	nothing_to_show = "No practice sessions in the next two weeks"

	def __init__(self, activities: ActivitiesProvider, settings: dict, default_seconds: float) -> None:
		self.activities = activities
		self.seconds = settings.get("seconds", default_seconds)
		self.days_ahead = settings.get("days_ahead", DAYS_AHEAD)

	def sessions(self, now: datetime) -> list[dict]:
		today = now.date()
		last = today + timedelta(days=self.days_ahead)
		sessions = []
		for activity in self.activities.activities:
			if not PRACTICE.search(activity.title) or not today <= activity.day <= last:
				continue
			if activity.day == today and activity.time:
				start = datetime.combine(today, datetime.strptime(activity.time, "%H:%M").time())
				if now > start + SHOWN_AFTER_START:
					continue
			course = PRACTICE.sub(" ", activity.title).strip(" -:") or "Practice session"
			sessions.append({"course": course[:1].upper() + course[1:], "day": activity.day, "time": activity.time,
				"room": activity.location or "Room TBA", "today": activity.day == today})
		return sessions[:MAX_SESSIONS]

	def slides(self, now: datetime) -> list[Slide]:
		sessions = self.sessions(now)
		if not sessions:
			return []
		height = ticket_size(len(sessions))
		return [Slide("practice.html", self.seconds, {
			"sessions": [session | {"size": course_size(session["course"], height)} for session in sessions],
			"ticket_height": round(height, 1),
			"date_width": date_width(height),
			"gap": TICKET_GAP,
		})]
