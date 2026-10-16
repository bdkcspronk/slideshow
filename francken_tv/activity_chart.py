"""The daily "Francken activity tracker" chart: who was in the room when today.

This file turns sightings into rows, bars and timings; templates/slides/presence.html and
the "Activity chart" styles in style.css draw them (the bars grow in, beer fizzes, the nyan
cat rides its rainbow). Each person gets a row; every stretch of time they were around is a
bar. The bar's look comes from their entry in config/devices.json:

	"color":           "#fcd303", or a list of colours for a gradient
	"style":           "round corners" (default), "square corners", "striped", "nyan cat",
	                   "rainbow" (nyan cat without the cat), "beer", "board",
	                   or a list combining one of those with "glow"
	"stripe_color":    colour (or gradient list) of the stripes for "striped"
	                   (or give "color" as [[bar colours], [stripe colours]])
	"thickness":       stripe thickness in pixels for "striped"
	"x_offset":        horizontal offset of the nyan cat, in % of its width
	"foam_max_width":  maximum width of the beer foam in pixels

People without a colour get a stable random bright one.
"""

from __future__ import annotations

import colorsys
import hashlib
import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from .devices import Device
from .presence_store import Sighting

TEXT_COLOR = "#ECEFF1"
FALLBACK_SATURATION_RANGE = (0.65, 0.9)
FALLBACK_BRIGHTNESS_RANGE = (0.85, 1.0)
BUCKET = timedelta(minutes=5)          # sightings are grouped per 5 minutes
MAX_GAP = timedelta(minutes=10)        # gaps up to this long don't split a bar
SHAPES = {"round corners", "square corners", "striped", "nyan cat", "rainbow", "beer", "board"}
CHART_LEAD = timedelta(hours=1)        # the chart starts this long before the first arrival
GROW_SECONDS = 4.0                     # the bars draw themselves across the chart in this time
GROW_STARTS = 0.8                      # ...starting after the slide has faded in


@dataclass
class MarkerStyle:
	color: str | list | None = None
	shape: str = "round corners"
	glow: bool = False
	stripe_color: str | list = TEXT_COLOR
	stripe_thickness: float | None = None
	nyan_cat_x_offset: float = 0
	beer_foam_max_width: float | None = None


@dataclass
class Bar:
	start: datetime
	end: datetime
	row: int
	style: MarkerStyle
	is_latest: bool


@dataclass
class ChartData:
	names: list[str] = field(default_factory=list)
	bars: list[Bar] = field(default_factory=list)
	latest_sighting: datetime | None = None


def parse_style(options: dict) -> MarkerStyle:
	color = options.get("color", options.get("gradient"))
	configured = options.get("style", "round corners")
	styles = [configured] if isinstance(configured, str) else configured if isinstance(configured, list) else []
	style = MarkerStyle(glow="glow" in styles)
	style.shape = next((s for s in styles if s in SHAPES), "round corners")

	stripe_color = options.get("stripe_color")
	if style.shape == "striped" and isinstance(color, list) and color and isinstance(color[0], list):
		stripe_color = color[1] if len(color) > 1 else None
		color = color[0]
	if isinstance(color, list):
		style.color = color if len(color) >= 2 else (color[0] if color else None)
	elif isinstance(color, str):
		style.color = color
	if isinstance(stripe_color, list):
		if len(stripe_color) >= 2:
			style.stripe_color = stripe_color
		elif stripe_color:
			style.stripe_color = stripe_color[0]
	elif isinstance(stripe_color, str):
		style.stripe_color = stripe_color

	thickness = options.get("thickness")
	if isinstance(thickness, (int, float)) and thickness > 0:
		style.stripe_thickness = thickness
	x_offset = options.get("x_offset", 0)
	if isinstance(x_offset, (int, float)):
		style.nyan_cat_x_offset = x_offset
	foam = options.get("foam_max_width")
	if isinstance(foam, (int, float)) and foam > 0:
		style.beer_foam_max_width = foam
	return style


def generate_bright_color(identifier: str) -> str:
	"""A stable, bright colour for a device without a configured colour."""
	digest = hashlib.sha256(identifier.encode("utf-8")).digest()
	hue = int.from_bytes(digest[0:2], "big") / 65535
	saturation = FALLBACK_SATURATION_RANGE[0] + digest[2] / 255 * (FALLBACK_SATURATION_RANGE[1] - FALLBACK_SATURATION_RANGE[0])
	brightness = FALLBACK_BRIGHTNESS_RANGE[0] + digest[3] / 255 * (FALLBACK_BRIGHTNESS_RANGE[1] - FALLBACK_BRIGHTNESS_RANGE[0])
	red, green, blue = colorsys.hsv_to_rgb(hue, saturation, brightness)
	return "#{:02X}{:02X}{:02X}".format(round(red * 255), round(green * 255), round(blue * 255))


def floor_to_bucket(moment: datetime) -> datetime:
	return moment.replace(minute=moment.minute - moment.minute % 5, second=0, microsecond=0)


def floor_to_quarter(moment: datetime) -> datetime:
	return moment.replace(minute=moment.minute - moment.minute % 15, second=0, microsecond=0)


def merge_into_blocks(buckets: list[datetime]) -> list[tuple[datetime, datetime]]:
	"""Sorted 5-minute buckets -> (start, end) stretches, bridging gaps of up to 10 minutes."""
	blocks = []
	start = previous = buckets[0]
	for current in buckets[1:]:
		if current - previous > MAX_GAP:
			blocks.append((start, previous + BUCKET))
			start = current
		previous = current
	blocks.append((start, previous + BUCKET))
	return blocks


def prepare(sightings: list[Sighting], devices: dict[str, Device]) -> ChartData:
	"""Turn today's sightings into rows and bars. Rows are ordered by who arrived first."""
	data = ChartData()
	if not sightings:
		return data
	first_mac: dict[str, str] = {}
	buckets: dict[str, set[datetime]] = {}
	for sighting in sorted(sightings, key=lambda s: s.time):
		first_mac.setdefault(sighting.name, sighting.mac.upper())
		buckets.setdefault(sighting.name, set()).add(floor_to_bucket(sighting.time))
	data.names = list(first_mac)
	data.latest_sighting = max(s.time for s in sightings)

	for row, name in enumerate(data.names):
		mac = first_mac[name]
		device = devices.get(mac)
		style = parse_style(device.options) if device else MarkerStyle()
		if style.color is None:
			style.color = generate_bright_color(mac or name)
		blocks = merge_into_blocks(sorted(buckets[name]))
		for index, (start, end) in enumerate(blocks):
			data.bars.append(Bar(start, end, row, style, is_latest=index == len(blocks) - 1))
	return data


def css_colour(colour: str | list) -> str:
	"""A CSS background for a colour or a gradient list."""
	return colour if isinstance(colour, str) else f"linear-gradient(90deg, {', '.join(colour)})"


def bar_look(style: MarkerStyle, width: float, seed: str) -> dict:
	"""How a person's bar looks (templates/slides/bar.html): its shape, colour, stripes, glow and beer.
	Shared by the activity chart and the leaderboard. width: in % of the chart, for the bubbles."""
	look = {"shape": style.shape.replace(" ", "-"), "glow": style.glow, "background": css_colour(style.color)}
	if style.glow:
		look["glow_colour"] = style.color[len(style.color) // 2] if isinstance(style.color, list) else style.color
	if style.shape in ("striped", "board"):
		look["stripes"] = "#0057B8" if style.shape == "board" else css_colour(style.stripe_color)
		look["stripe_width"] = f"{max(4, style.stripe_thickness * 1.5):.1f}px" if style.stripe_thickness else None
	if style.shape == "beer":
		look["foam"] = f"min(28%, {style.beer_foam_max_width:.0f}px)" if style.beer_foam_max_width else "28%"
		rng = random.Random(seed)   # the same bubbles every time this bar is drawn
		# Bubbles drift from the left towards the foam on the right, at roughly the same speed in
		# every bar (so longer bars take longer). The negative wait starts each one somewhere along
		# the way, so the bar is full of bubbles straight away.
		travel = max(1.5, width * 0.13)
		look["bubbles"] = []
		for _ in range(max(2, min(14, round(width * 1.5)))):
			duration = round(travel * rng.uniform(0.8, 1.25), 2)
			look["bubbles"].append({"y": round(rng.uniform(12, 72), 1), "size": round(rng.uniform(0.7, 1.0) * 24, 1),
				"duration": duration, "wait": round(-rng.uniform(0, duration), 2)})
	return look


def chart_view(sightings: list[Sighting], devices: dict[str, Device], now: datetime) -> dict | None:
	"""Everything templates/slides/presence.html needs, or None if nobody was seen today."""
	data = prepare(sightings, devices)
	if not data.names:
		return None
	first = min(bar.start for bar in data.bars)
	# The chart starts an hour before the first person arrived (on a quarter hour, so the grid lines line up).
	start = floor_to_quarter(first - CHART_LEAD)
	end = max(now, data.latest_sighting) + timedelta(minutes=30)
	span = (end - start).total_seconds()
	percent = lambda moment: round((moment - start).total_seconds() / span * 100, 3)

	# Bars with the same gradient share one gradient across the chart (as in the old chart).
	gradient_extent: dict[tuple, tuple[float, float]] = {}
	for bar in data.bars:
		if isinstance(bar.style.color, list) and bar.style.shape not in ("nyan cat", "rainbow", "beer", "board"):
			key = tuple(bar.style.color)
			left, right = gradient_extent.get(key, (100.0, 0.0))
			gradient_extent[key] = (min(left, percent(bar.start)), max(right, percent(bar.end)))

	bars = []
	for bar in data.bars:
		style = bar.style
		left, width = percent(bar.start), max(percent(bar.end) - percent(bar.start), 0.2)
		view = {
			**bar_look(style, width, seed=f"{bar.row}-{bar.start}"),
			"row": bar.row, "left": left, "width": width,
			# Grow at a steady speed from left to right, like time playing back.
			"delay": round(GROW_STARTS + left / 100 * GROW_SECONDS, 2),
			"grow": round(max(width / 100 * GROW_SECONDS, 0.25), 2),
			"nyan_cat": style.shape == "nyan cat" and bar.is_latest, "cat_offset": style.nyan_cat_x_offset,
		}
		if isinstance(style.color, list) and tuple(style.color) in gradient_extent:
			group_left, group_right = gradient_extent[tuple(style.color)]
			group_width = max(group_right - group_left, width)
			view["gradient_size"] = round(group_width / width * 100, 2)
			view["gradient_position"] = round((left - group_left) / (group_width - width) * 100, 2) if group_width > width else 0
		bars.append(view)

	hour = start.replace(minute=0, second=0, microsecond=0)
	grid, ticks = [], []
	moment = hour
	while moment <= end:
		if moment >= start:
			kind = "hour" if moment.minute == 0 else "half" if moment.minute == 30 else "quarter"
			grid.append({"left": percent(moment), "kind": kind})
			if moment.minute == 0:
				ticks.append({"left": percent(moment), "label": moment.strftime("%H:%M")})
		moment += timedelta(minutes=15)
	return {"names": data.names, "bars": bars, "grid": grid, "ticks": ticks}


def time_in_room(sightings: list[Sighting]) -> dict[str, tuple[timedelta, set[date]]]:
	"""Per person: total time in the room (the same stretches as the chart) and the days present."""
	buckets: dict[tuple[str, date], set[datetime]] = {}
	for sighting in sightings:
		buckets.setdefault((sighting.name, sighting.time.date()), set()).add(floor_to_bucket(sighting.time))
	totals: dict[str, tuple[timedelta, set[date]]] = {}
	for (name, day), times in buckets.items():
		duration = sum((end - start for start, end in merge_into_blocks(sorted(times))), timedelta())
		total, days = totals.get(name, (timedelta(), set()))
		totals[name] = (total + duration, days | {day})
	return totals
