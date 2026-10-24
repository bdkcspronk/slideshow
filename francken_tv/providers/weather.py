"""The weather slide: the weather now and the next days at Zernike (open-meteo.com), with Buienradar's
rain forecast for the next two hours (the same as their app). One of the info slides: the scheduler shows
one of news, weather, buses and timetable per round (rotation.take_turns).

After bieruur (rotation.daytime_only) only a rain warning (rain.html), when rain is expected within two hours.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta

import requests

from ..config import parse_time
from ..slides import Provider, Slide

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "FranckenTV-slideshow/1.0 (the TV in the T.F.V. 'Professor Francken' room)"}
ZERNIKE = (53.2406, 6.5364)
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
RAIN_URL = "https://gpsgadget.buienradar.nl/data/raintext"


# WMO weather codes (open-meteo): description and an icon.
WEATHER_CODES = {
	0: ("Clear sky", "☀️"), 1: ("Mainly clear", "🌤️"), 2: ("Partly cloudy", "⛅"), 3: ("Overcast", "☁️"),
	45: ("Fog", "🌫️"), 48: ("Freezing fog", "🌫️"),
	51: ("Light drizzle", "🌦️"), 53: ("Drizzle", "🌦️"), 55: ("Heavy drizzle", "🌧️"), 56: ("Freezing drizzle", "🌧️"), 57: ("Freezing drizzle", "🌧️"),
	61: ("Light rain", "🌦️"), 63: ("Rain", "🌧️"), 65: ("Heavy rain", "🌧️"), 66: ("Freezing rain", "🌧️"), 67: ("Freezing rain", "🌧️"),
	71: ("Light snow", "🌨️"), 73: ("Snow", "🌨️"), 75: ("Heavy snow", "❄️"), 77: ("Snow grains", "🌨️"),
	80: ("Rain showers", "🌦️"), 81: ("Rain showers", "🌧️"), 82: ("Heavy showers", "🌧️"), 85: ("Snow showers", "🌨️"), 86: ("Snow showers", "🌨️"),
	95: ("Thunderstorm", "⛈️"), 96: ("Thunderstorm with hail", "⛈️"), 99: ("Thunderstorm with hail", "⛈️"),
}
NIGHT_ICONS = {"☀️": "🌙", "🌤️": "🌙", "⛅": "☁️"}
# The animated background of the weather slide for each WMO code (default: cloudy).
WEATHER_SCENES = {
	0: "clear", 1: "clear", 2: "partly", 3: "cloudy", 45: "fog", 48: "fog",
	51: "drizzle", 53: "drizzle", 55: "drizzle", 56: "drizzle", 57: "drizzle",
	61: "rain", 63: "rain", 65: "heavy-rain", 66: "rain", 67: "heavy-rain", 80: "rain", 81: "rain", 82: "heavy-rain",
	71: "snow", 73: "snow", 75: "snow", 77: "snow", 85: "snow", 86: "snow",
	95: "storm", 96: "storm", 99: "storm",
}
WIND_DIRECTIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def weather_look(code: int, is_day: bool = True) -> tuple[str, str]:
	text, icon = WEATHER_CODES.get(code, ("", "🌡️"))
	return text, icon if is_day else NIGHT_ICONS.get(icon, icon)


@dataclass
class Day:
	day: date
	high: float
	low: float
	text: str
	icon: str
	rain_chance: int   # %, the highest of the day


@dataclass
class Weather:
	temperature: float
	feels_like: float
	text: str
	icon: str
	wind_kmh: float
	wind_from: str     # "NE"
	days: list[Day] = field(default_factory=list)   # today first
	rain: list[tuple[str, float]] = field(default_factory=list)   # ("14:35", mm/h) per 5 minutes, two hours ahead
	code: int = 3      # the WMO weather code now
	is_day: bool = True

	@property
	def rain_summary(self) -> str:
		return rain_summary(self.rain)

	@property
	def scene(self) -> str:
		"""The weather slide's animated background: clear, partly, cloudy, fog, drizzle, rain, heavy-rain, snow or storm."""
		return WEATHER_SCENES.get(self.code, "cloudy")


def parse_weather(data: dict) -> Weather:
	current = data["current"]
	text, icon = weather_look(current["weather_code"], bool(current.get("is_day", 1)))
	daily = data["daily"]
	days = [Day(date.fromisoformat(day), high, low, *weather_look(code), chance or 0)
		for day, high, low, code, chance in zip(daily["time"], daily["temperature_2m_max"], daily["temperature_2m_min"],
			daily["weather_code"], daily["precipitation_probability_max"])]
	return Weather(
		temperature=current["temperature_2m"],
		feels_like=current["apparent_temperature"],
		text=text,
		icon=icon,
		wind_kmh=current["wind_speed_10m"],
		wind_from=WIND_DIRECTIONS[round(current["wind_direction_10m"] / 45) % 8],
		days=days,
		code=current["weather_code"],
		is_day=bool(current.get("is_day", 1)),
	)


def parse_rain(text: str) -> list[tuple[str, float]]:
	"""Buienradar's 'value|HH:MM' lines as (HH:MM, mm/h); the value is 0-255, 0 is dry."""
	rain = []
	for line in text.splitlines():
		value, _, time = line.strip().partition("|")
		if value.isdigit() and time:
			rain.append((time, 0.0 if int(value) == 0 else round(10 ** ((int(value) - 109) / 32), 2)))
	return rain


def rain_words(mm: float) -> str:
	return "light rain" if mm < 1 else "rain" if mm < 4 else "heavy rain"


RAIN_LEVELS = [("Light", 0.1), ("Medium", 1.0), ("Heavy", 4.0)]   # where each kind of rain starts, mm/h


def rain_top(rain: list[tuple[str, float]]) -> float:
	return max([mm for _, mm in rain] + [2.0])   # the chart's top: at least 2 mm/h


def rain_bars(rain: list[tuple[str, float]]) -> list[dict]:
	"""The rain per 5 minutes, with its height in the chart (0-100) relative to the chart's top (square
	root, so light rain still shows)."""
	top = rain_top(rain)
	return [{"time": time, "mm": mm, "level": rain_level(mm), "height": round(100 * math.sqrt(mm / top), 1)} for time, mm in rain]


def smooth_path(points: list[tuple[float, float]]) -> str:
	"""An SVG path through the points as a smooth curve (Catmull-Rom), never dipping below the
	bottom (y = 100) or above the top (y = 0)."""
	d = f"M{points[0][0]:.2f},{points[0][1]:.2f}"
	for i in range(len(points) - 1):
		p0, p1, p2, p3 = points[max(i - 1, 0)], points[i], points[i + 1], points[min(i + 2, len(points) - 1)]
		c1 = (p1[0] + (p2[0] - p0[0]) / 6, min(100, max(0, p1[1] + (p2[1] - p0[1]) / 6)))
		c2 = (p2[0] - (p3[0] - p1[0]) / 6, min(100, max(0, p2[1] - (p3[1] - p1[1]) / 6)))
		d += f" C{c1[0]:.2f},{c1[1]:.2f} {c2[0]:.2f},{c2[1]:.2f} {p2[0]:.2f},{p2[1]:.2f}"
	return d


def rain_chart(rain: list[tuple[str, float]]) -> dict | None:
	"""The line chart of the rain (rain_chart.html), in a 100 x 100 SVG box: the line, the area under
	it and the times along the bottom, every half hour."""
	if len(rain) < 2:
		return None
	bars = rain_bars(rain)
	points = [(100 * i / (len(bars) - 1), 100 - bar["height"]) for i, bar in enumerate(bars)]
	line = smooth_path(points)
	return {"line": line, "area": f"{line} L100,100 L0,100 Z",
		"times": [{"x": round(points[i][0], 2), "time": bars[i]["time"]} for i in range(0, len(bars), 6)]}


def rain_lines(rain: list[tuple[str, float]]) -> list[dict]:
	"""Lines across the rain chart where light, medium and heavy rain start, as high as a bar of that
	much rain; only those within the chart, and none when it stays dry."""
	if not any(mm >= 0.1 for _, mm in rain):
		return []
	top = rain_top(rain)
	return [{"label": label, "height": round(100 * math.sqrt(mm / top), 1)} for label, mm in RAIN_LEVELS if mm <= top]


def rain_level(mm: float) -> str:
	"""For the chart's colours: "dry", "light" (< 1 mm/h), "medium" (< 4) or "heavy"."""
	return "dry" if mm < 0.1 else "light" if mm < 1 else "medium" if mm < 4 else "heavy"


DRY_STRETCH = 6        # "dry from" only when it then stays dry this many five minutes (half an hour)...
DRY_STRETCH_AT_END = 3   # ...or, at the end of the forecast, at least this many (a quarter)


def dry_from(rain: list[tuple[str, float]]) -> str | None:
	"""When it stops raining for a while: the start of the first dry half hour, not the first dry
	five minutes between two showers. None if there's no such stretch in the forecast."""
	wet = [mm >= 0.1 for _, mm in rain]
	for i in range(len(wet)):
		stretch = wet[i:i + DRY_STRETCH]
		if not any(stretch) and (len(stretch) == DRY_STRETCH or len(stretch) >= DRY_STRETCH_AT_END):
			return rain[i][0]
	return None


def rain_summary(rain: list[tuple[str, float]]) -> str:
	"""'Dry for the next 2 hours', 'Light rain from 14:35', 'Rain now, dry from 15:10'"""
	wet = [mm >= 0.1 for _, mm in rain]
	if not rain or not any(wet):
		return "Dry for the next 2 hours"
	heaviest = max(mm for _, mm in rain)
	if wet[0]:
		dry = dry_from(rain)
		return f"{rain_words(heaviest).capitalize()} now, dry from {dry}" if dry else f"{rain_words(heaviest).capitalize()} for the next 2 hours"
	start = next(time for (time, _), is_wet in zip(rain, wet) if is_wet)
	return f"{rain_words(heaviest).capitalize()} from {start}"


class WeatherProvider(Provider):
	name = "weather"
	title = "Weather"
	nothing_to_show = "No weather yet"
	refresh_seconds = 10 * 60

	def __init__(self, settings: dict, default_seconds: float) -> None:
		self.seconds = settings.get("seconds", default_seconds)
		self.place = settings.get("place", "Zernike campus")
		self.location = settings.get("location", list(ZERNIKE))
		self.weather: Weather | None = None

	def refresh(self, now: datetime) -> None:
		lat, lon = self.location
		response = requests.get(WEATHER_URL, headers=HEADERS, timeout=20, params={
			"latitude": lat, "longitude": lon, "timezone": "Europe/Amsterdam", "forecast_days": 7,
			"current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,wind_direction_10m,is_day",
			"daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max",
		})
		response.raise_for_status()
		weather = parse_weather(response.json())
		try:
			rain = requests.get(RAIN_URL, headers=HEADERS, timeout=20, params={"lat": round(lat, 2), "lon": round(lon, 2)})
			rain.raise_for_status()
			weather.rain = parse_rain(rain.text)
		except requests.RequestException as error:   # no rain forecast: the rest still shows
			log.warning("Could not fetch the rain forecast: %s", error)
		self.weather = weather

	def slides(self, now: datetime) -> list[Slide]:
		data = self.weather_data(now)
		return [Slide("weather.html", self.seconds, data, update=lambda when: self.weather_data(when) or data)] if data else []

	def outside_daytime_slides(self, now: datetime) -> list[Slide]:
		"""After bieruur and at night (rotation.daytime_only): a rain warning (rain.html) when rain is
		expected within two hours."""
		data = self.rain_data(now)
		return [Slide("rain.html", self.seconds, data, update=lambda when: self.rain_data(when) or data)] if data else []

	def rain_preview(self, now: datetime) -> Slide | None:
		"""For /preview/rain: the rain warning, with the real forecast, or when it stays dry with an
		example shower starting in half an hour (marked as an example)."""
		if self.weather is None:
			return None
		if self.rain_coming(now):
			return Slide("rain.html", self.seconds, self.rain_data(now))
		start = now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % 5)
		shower = [0] * 6 + [0.2, 0.5, 1.1, 2.3, 3.6, 2.8, 1.9, 1.2, 0.6, 0.3, 0.1] + [0] * 7
		real = self.weather
		self.weather = replace(real, rain=[((start + timedelta(minutes=5 * i)).strftime("%H:%M"), mm) for i, mm in enumerate(shower)])
		try:
			data = self.rain_data(now) | {"example": True}
		finally:
			self.weather = real
		return Slide("rain.html", self.seconds, data)

	def upcoming_rain(self, now: datetime) -> list[tuple[str, float]]:
		"""Buienradar's forecast from the current five minutes on: it's fetched every 10 minutes, so
		its first values may be past already. At most the next two hours."""
		if self.weather is None or not self.weather.rain:
			return []
		first = datetime.combine(now.date(), parse_time(self.weather.rain[0][0]))
		if first > now + timedelta(hours=12):   # fetched just before midnight
			first -= timedelta(days=1)
		upcoming = []
		for hhmm, mm in self.weather.rain:
			when = datetime.combine(first.date(), parse_time(hhmm))
			if when < first:   # after midnight
				when += timedelta(days=1)
			if now - timedelta(minutes=5) < when <= now + timedelta(hours=2):
				upcoming.append((hhmm, mm))
		return upcoming

	def rain_coming(self, now: datetime) -> bool:
		"""Rain in Buienradar's forecast for the next two hours (or now)."""
		return any(mm >= 0.1 for _, mm in self.upcoming_rain(now))

	def weather_data(self, now: datetime) -> dict | None:
		if self.weather is None:
			return None
		days = [day for day in self.weather.days if day.day >= now.date()][:6]   # today and the next five
		rain = self.upcoming_rain(now)
		return {"weather": self.weather, "place": self.place, "days": days, "today": now.date(), "rain": rain_bars(rain),
			"chart": rain_chart(rain), "rain_lines": rain_lines(rain), "rain_summary": rain_summary(rain)}

	def rain_data(self, now: datetime) -> dict | None:
		"""The rain warning (after bieruur): when, how heavy, and the chart; None when it stays dry."""
		rain = self.upcoming_rain(now)
		if not any(mm >= 0.1 for _, mm in rain):
			return None
		heaviest = max(mm for _, mm in rain)
		# The sky behind it: as heavy as the rain that's coming, or the thunderstorm that's already there.
		scene = "storm" if self.weather and self.weather.scene == "storm" else {"light rain": "drizzle", "rain": "rain"}.get(rain_words(heaviest), "heavy-rain")
		return {"summary": rain_summary(rain), "heaviest": rain_words(heaviest), "place": self.place,
			"rain": rain_bars(rain), "chart": rain_chart(rain), "rain_lines": rain_lines(rain), "weather": self.weather,
			"scene": scene, "is_day": self.weather.is_day if self.weather else True}

