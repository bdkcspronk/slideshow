"""The timetable slide: today's Applied Physics lectures, from rooster.rug.nl. The programmes are found
by name and year of study every refresh, because their ids change every academic year. One of the info
slides: the scheduler shows one of news, weather, buses and timetable per round (rotation.take_turns).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import requests

from ..slides import Provider, Slide

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "FranckenTV-slideshow/1.0 (the TV in the T.F.V. 'Professor Francken' room)"}
ROOSTER_URL = "https://rooster.rug.nl/maat/api/{year}"
TIMETABLE = [["BSc Applied Physics", 1], ["BSc Applied Physics", 2], ["BSc Applied Physics", 3], ["MSc Applied Physics", 1]]


def academic_year(day: date) -> str:
	"""'2026-2027' from September 2026 to August 2027."""
	start = day.year if day.month >= 9 else day.year - 1
	return f"{start}-{start + 1}"


@dataclass
class Lecture:
	start: datetime
	end: datetime
	course: str
	kind: str           # "Lecture", "Tutorial", ...
	rooms: list[str]

	@property
	def group(self) -> str:
		"""The colour group of the kind: "lecture", "tutorial", "practical", "exam" or "other"."""
		return KIND_GROUPS.get(self.kind.lower(), "other")


# rooster.rug.nl's kinds of activity, in colour groups (the timetable slide colours them; see style.css).
KIND_GROUPS = {
	"lecture": "lecture",
	"tutorial": "tutorial", "workshop": "tutorial", "q&a": "tutorial",
	"practical": "practical", "computer practical": "practical", "lab session": "practical", "projects": "practical",
	"exam": "exam", "exam digital": "exam", "midterm": "exam", "midterm digital": "exam",
	"resit": "exam", "resit digital": "exam", "inspection": "exam",
}
GENERIC_ROOM_NAMES = {"", "-", "collegezaal", "werkcollegezaal", "zaal", "lecture hall"}


def room_label(room: dict) -> str:
	"""'5161.0289', or '5113.0202 Max Gruberzaal' when the room has a name of its own."""
	code, name = room.get("code") or "", (room.get("displayNameEn") or "").strip()
	return f"{code} {name}".strip() if name.lower() not in GENERIC_ROOM_NAMES else code


def parse_timetable(events: list[dict], columns: dict[int, str]) -> dict[str, list[Lecture]]:
	"""rooster.rug.nl events per column (programme id -> "BSc 1"), in time order. Events that only
	differ in room (e.g. tutorial groups) become one, with all the rooms."""
	merged: dict[tuple, Lecture] = {}
	for event in events:
		start, end = datetime(*event["start"]), datetime(*event["end"])
		course = (event.get("courseOfferings") or [{}])[0].get("displayNameEn") or event.get("description") or ""
		kind = (event.get("activityType") or {}).get("displayNameEn", "")
		rooms = [label for room in event.get("rooms") or [] if (label := room_label(room))]
		for programme in event.get("programmeOfferings") or []:
			column = columns.get(programme.get("id"))
			if column is None:
				continue
			key = (column, start, end, course, kind)
			if key in merged:
				merged[key].rooms += [room for room in rooms if room not in merged[key].rooms]
			else:
				merged[key] = Lecture(start, end, course, kind, list(dict.fromkeys(rooms)))
	timetable: dict[str, list[Lecture]] = {column: [] for column in columns.values()}
	for (column, *_), lecture in sorted(merged.items(), key=lambda item: item[1].start):
		timetable[column].append(lecture)
	return timetable


def column_name(name: str, year: int) -> str:
	"""'BSc Applied Physics', 1 -> 'BSc 1'"""
	return f"{name.split()[0]} {year}"


class TimetableProvider(Provider):
	name = "timetable"
	title = "Timetable"
	nothing_to_show = "No lectures in the coming week"
	refresh_seconds = 3 * 60 * 60

	def __init__(self, settings: dict) -> None:
		self.seconds = settings.get("seconds", 25)   # the most to read of the info slides
		self.timetable_name = settings.get("name", "Applied Physics")
		self.programmes = settings.get("programmes", TIMETABLE)
		self.next_day_from = settings.get("next_day_from_hour", 18)
		self.timetable: dict[str, list[Lecture]] = {}

	def refresh(self, now: datetime) -> None:
		year = academic_year(now.date())
		api = ROOSTER_URL.format(year=year)
		columns = {}
		for name, year_of_study in self.programmes:
			response = requests.post(f"{api}/programme-offerings/search", headers=HEADERS, timeout=30,
				json={"searchText": name, "academicYear": year, "limit": 50})
			response.raise_for_status()
			normalised = " ".join(name.lower().split())
			match = next((programme for programme in response.json().get("results", [])
				if " ".join(programme["displayNameEn"].lower().split()).startswith(normalised)
				and programme.get("yearOfStudy") == year_of_study and programme.get("specialisation") == "Base programme"), None)
			if match is None:
				log.warning("No programme %r year %s in rooster.rug.nl %s", name, year_of_study, year)
				continue
			columns[match["id"]] = column_name(name, year_of_study)
		if not columns:
			raise RuntimeError(f"none of the programmes found in the {year} timetable")
		response = requests.post(f"{api}/schedule/generate", headers=HEADERS, timeout=60,
			json={"objects": list(columns), "courseOfferings": []})
		response.raise_for_status()
		self.timetable = parse_timetable(response.json().get("results", []), columns)

	def slides(self, now: datetime) -> list[Slide]:
		data = self.timetable_data(now)
		return [Slide("timetable.html", self.seconds, data, update=lambda when: self.timetable_data(when) or data)] if data else []

	def timetable_data(self, now: datetime) -> dict | None:
		"""Today's lectures that aren't over yet, until the evening; else those of the next day that has
		any (within a week). A lecture from 9:00 to 11:00 is gone at 11:00."""
		if not self.timetable:
			return None
		start_day = now.date() if now.hour < self.next_day_from else now.date() + timedelta(days=1)
		for offset in range(8):
			day = start_day + timedelta(days=offset)
			columns = {column: [lecture for lecture in lectures if lecture.start.date() == day and lecture.end > now] for column, lectures in self.timetable.items()}
			if any(columns.values()):
				label = "today" if day == now.date() else "tomorrow" if day == now.date() + timedelta(days=1) else day.strftime("%A %-d %B")
				return {"name": self.timetable_name, "day": label, "columns": columns, "now": now}
		return None
