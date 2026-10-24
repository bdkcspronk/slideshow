"""The buses slide: the next departures from Aletta Jacobshal, live from OVapi (v0.ovapi.nl, the same
national real-time data 9292 shows); the stop is a list of timing point codes (from the national stop
list, GTFS stops.txt). One of the info slides: the scheduler shows one of news, weather, buses and
timetable per round (rotation.take_turns).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import requests

from ..slides import Provider, Slide

HEADERS = {"User-Agent": "FranckenTV-slideshow/1.0 (the TV in the T.F.V. 'Professor Francken' room)"}
OVAPI_URL = "http://v0.ovapi.nl/tpc/{codes}"
ALETTA_JACOBSHAL = ["10004120"]   # Groningen, Aletta Jacobshal: the side towards the city centre (10004110 is the other side)
# Qbuzz's colours for the Groningen city lines (Qlink), as on their site and the buses: [background, text].
# From route_color/route_text_color in the national GTFS (gtfs.ovapi.nl/nl, routes.txt); the regional lines
# (107, 109, 171, ...) have none there and keep the slide's blue.
BUS_LINE_COLORS = {
	"1": ["#00be46", "#000000"], "2": ["#8cdc32", "#000000"], "3": ["#1078be", "#ffffff"],
	"4": ["#00bcf2", "#000000"], "5": ["#b400be", "#ffffff"], "6": ["#c85aff", "#ffffff"],
	"9": ["#ff00ff", "#ffffff"], "11": ["#00be46", "#000000"], "15": ["#ff5f00", "#000000"],
	"18": ["#99c200", "#000000"],
}


@dataclass
class Departure:
	line: str
	destination: str
	planned: datetime
	expected: datetime
	cancelled: bool = False

	@property
	def delay(self) -> int:
		"""Minutes late (0 if on time or early)."""
		return max(0, round((self.expected - self.planned).total_seconds() / 60))


def parse_departures(data: dict) -> list[Departure]:
	"""All passes at the asked timing points (OVapi /tpc/...), soonest first."""
	departures = []
	for timing_point in data.values():
		for item in (timing_point.get("Passes") or {}).values():
			if item.get("JourneyStopType") == "LAST":   # arriving at its last stop: not departing
				continue
			departures.append(Departure(
				line=item["LinePublicNumber"],
				destination=item["DestinationName50"],
				planned=datetime.fromisoformat(item["TargetDepartureTime"]),
				expected=datetime.fromisoformat(item["ExpectedDepartureTime"]),
				cancelled=item.get("TripStopStatus") == "CANCEL",
			))
	return sorted(departures, key=lambda departure: departure.expected)


class BusesProvider(Provider):
	name = "buses"
	title = "Buses"
	nothing_to_show = "No buses to catch right now"
	refresh_seconds = 60   # the minutes also count down by themselves in between

	def __init__(self, settings: dict, default_seconds: float) -> None:
		self.seconds = settings.get("seconds", default_seconds)
		self.stop_name = settings.get("stop_name", "Aletta Jacobshal")
		self.stop_codes = settings.get("stop_codes", ALETTA_JACOBSHAL)
		self.departures_shown = settings.get("departures_shown", 8)
		self.walk_minutes = settings.get("walk_minutes", 2)   # from the association to the stop
		self.line_colors = settings.get("line_colors", BUS_LINE_COLORS)
		self.departures: list[Departure] = []

	def refresh(self, now: datetime) -> None:
		response = requests.get(OVAPI_URL.format(codes=",".join(self.stop_codes)), headers=HEADERS, timeout=20)
		response.raise_for_status()
		self.departures = parse_departures(response.json())

	def slides(self, now: datetime) -> list[Slide]:
		# Worked out again when shown: the round is planned ahead, and buses leave meanwhile.
		data = self.buses_data(now)
		return [Slide("buses.html", self.seconds, data, update=lambda when: self.buses_data(when) or data)] if data else []

	def buses_data(self, now: datetime) -> dict | None:
		"""The buses that can still be caught: those leaving at least walk_minutes from now. One you have to
		leave for right away (less than a minute to spare) is a "last call"."""
		catchable = now + timedelta(minutes=self.walk_minutes)
		upcoming = [departure for departure in self.departures if departure.expected >= catchable]
		if not upcoming:
			return None
		shown = []
		for departure in upcoming[: self.departures_shown]:
			minutes = int((departure.expected - now).total_seconds() // 60)
			shown.append({"departure": departure, "minutes": minutes, "colors": self.line_colors.get(departure.line),
				"last_call": departure.expected < catchable + timedelta(minutes=1)})
		return {"stop": self.stop_name, "departures": shown, "walk_minutes": self.walk_minutes}
