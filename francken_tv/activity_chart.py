"""Draws the daily "Francken activity tracker" chart: who was in the room when today.

Each person gets a row; every stretch of time they were around is a bar. The bar's look
comes from their entry in config/devices.json:

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
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")   # no window; render straight to a file

import matplotlib.dates as mdates
import matplotlib.image
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.path import Path as MplPath
from matplotlib.transforms import IdentityTransform

from .devices import Device
from .presence_store import Sighting

DEFAULT_COLOR = "#00E676"
GRID_COLOR = "#263238"
BACKGROUND_COLOR = "#151722"
TEXT_COLOR = "#ECEFF1"
FALLBACK_SATURATION_RANGE = (0.65, 0.9)
FALLBACK_BRIGHTNESS_RANGE = (0.85, 1.0)
FIGURE_SIZE = (19.2, 10.8)
FIGURE_DPI = 100
CORNER_RADIUS = 8
CURVE_FACTOR = 0.5522848
VERTICAL_AXIS_PADDING = 1.0
SUBPLOT_MARGINS = {"left": 0.12, "right": 0.98, "bottom": 0.12, "top": 0.88}
BUCKET = timedelta(minutes=5)          # sightings are grouped per 5 minutes
MAX_GAP = timedelta(minutes=10)        # gaps up to this long don't split a bar
SHAPES = {"round corners", "square corners", "striped", "nyan cat", "rainbow", "beer", "board"}


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


def render_chart(sightings: list[Sighting], devices: dict[str, Device], now: datetime, output: Path,
		starts_at: time = time(8, 0), nyan_cat_path: Path | None = None) -> bool:
	"""Draw today's chart to `output` (PNG). Returns False if there is nothing to draw."""
	data = prepare(sightings, devices)
	if not data.names:
		return False
	nyan_cat_image = matplotlib.image.imread(nyan_cat_path) if nyan_cat_path and nyan_cat_path.is_file() else None
	today = now.date()

	with plt.style.context("dark_background"):
		fig, ax = plt.subplots(figsize=FIGURE_SIZE, dpi=FIGURE_DPI, facecolor=BACKGROUND_COLOR)
		try:
			ax.set_facecolor(BACKGROUND_COLOR)
			ax.set_axisbelow(True)   # grid lines behind the bars
			ax.set_xlim(
				mdates.date2num(datetime.combine(today, starts_at)),
				mdates.date2num(max(now, data.latest_sighting) + timedelta(minutes=30)),
			)
			ax.set_ylim(-VERTICAL_AXIS_PADDING, len(data.names) - 1 + VERTICAL_AXIS_PADDING)
			ax.set_yticks(range(len(data.names)))
			ax.set_yticklabels(data.names, fontsize=20, fontweight="normal", color=TEXT_COLOR)
			ax.invert_yaxis()
			ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
			ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
			ax.tick_params(axis="x", colors=TEXT_COLOR, labelsize=20, pad=8)
			ax.tick_params(axis="y", colors=TEXT_COLOR, pad=12)
			for spine in ax.spines.values():
				spine.set_visible(False)
			draw_grid(ax, datetime.combine(today, starts_at), now + timedelta(minutes=5))
			ax.set_title("FRANCKEN ACTIVITY TRACKER", fontsize=25, fontweight="bold", color=TEXT_COLOR, loc="left", pad=25)
			fig.autofmt_xdate()
			fig.subplots_adjust(**SUBPLOT_MARGINS)

			# Bars are drawn in screen pixels so corners stay round; that needs the final layout first.
			fig.canvas.draw()
			gradient_groups: dict[tuple, dict] = {}
			rng = np.random.default_rng()
			for bar in data.bars:
				draw_bar(ax, bar, gradient_groups, rng, nyan_cat_image)
			draw_gradient_groups(ax, gradient_groups)

			output.parent.mkdir(parents=True, exist_ok=True)
			temporary = output.with_suffix(".tmp.png")
			fig.savefig(temporary, dpi=FIGURE_DPI, facecolor=fig.get_facecolor(), edgecolor="none")
			temporary.replace(output)   # the web server never sees a half-written file
		finally:
			plt.close(fig)
	return True


def draw_grid(ax, start: datetime, end: datetime) -> None:
	"""Vertical lines every 15 minutes, stronger on the half hour and hour."""
	moment = start
	while moment <= end:
		width, alpha = (2.0, 0.9) if moment.minute == 0 else (1.3, 0.75) if moment.minute == 30 else (0.7, 0.5)
		ax.axvline(moment, linestyle="-", linewidth=width, color=GRID_COLOR, alpha=alpha, zorder=1)
		moment += timedelta(minutes=15)
	ax.yaxis.grid(True, linestyle="-", color=GRID_COLOR, alpha=0.3, zorder=1)


def rounded_rectangle(x0: float, y0: float, x1: float, y1: float, radius: float) -> MplPath:
	curve = radius * CURVE_FACTOR
	return MplPath([
		(x0 + radius, y0), (x1 - radius, y0),
		(x1 - radius + curve, y0), (x1, y0 + radius - curve), (x1, y0 + radius),
		(x1, y1 - radius),
		(x1, y1 - radius + curve), (x1 - radius + curve, y1), (x1 - radius, y1),
		(x0 + radius, y1),
		(x0 + radius - curve, y1), (x0, y1 - radius + curve), (x0, y1 - radius),
		(x0, y0 + radius),
		(x0, y0 + radius - curve), (x0 + radius - curve, y0), (x0 + radius, y0),
	], [
		MplPath.MOVETO, MplPath.LINETO,
		MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4,
		MplPath.LINETO,
		MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4,
		MplPath.LINETO,
		MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4,
		MplPath.LINETO,
		MplPath.CURVE4, MplPath.CURVE4, MplPath.CURVE4,
	])


def draw_bar(ax, bar: Bar, gradient_groups: dict, rng, nyan_cat_image) -> None:
	style = bar.style
	screen = IdentityTransform()
	height = 0.8
	y_pos = bar.row - height / 2
	x0, y0 = ax.transData.transform((mdates.date2num(bar.start), y_pos))
	x1, y1 = ax.transData.transform((mdates.date2num(bar.end), y_pos + height))
	x0, x1 = sorted((x0, x1))
	y0, y1 = sorted((y0, y1))
	radius = min(CORNER_RADIUS, abs(x1 - x0) / 2, abs(y1 - y0) / 2)

	if style.shape == "square corners":
		shape = patches.Rectangle((x0, y0), x1 - x0, y1 - y0, transform=screen, facecolor="none", edgecolor="none", zorder=3)
	else:
		shape = patches.PathPatch(rounded_rectangle(x0, y0, x1, y1, radius), transform=screen, facecolor="none", edgecolor="none", zorder=3)

	if style.glow:
		glow_color = style.color[len(style.color) // 2] if isinstance(style.color, list) else style.color
		glow_width = max(4.0, min(18.0, (y1 - y0) * 0.22))
		for width, alpha in ((glow_width, 0.08), (glow_width * 0.65, 0.14), (glow_width * 0.35, 0.24)):
			ax.add_patch(patches.PathPatch(
				shape.get_path(), transform=shape.get_transform(), facecolor="none", edgecolor=glow_color,
				linewidth=width, alpha=alpha, joinstyle="round", zorder=2,
			))

	if style.shape == "board":
		shape.set_facecolor("#D62828")
		ax.add_patch(shape)
	elif style.shape == "beer":
		draw_beer(ax, shape, style, x0, y0, x1, y1, rng)
	elif style.shape in {"nyan cat", "rainbow"}:
		rainbow = matplotlib.colors.LinearSegmentedColormap.from_list(
			"nyan_cat_rainbow", ["#E40303", "#FF8C00", "#FFED00", "#008026", "#004DFF", "#750787"],
		)
		ax.add_patch(shape)
		ax.imshow(rainbow(np.linspace(0, 1, 256))[:, None, :], extent=(x0, x1, y0, y1), origin="lower",
			aspect="auto", transform=screen, clip_path=shape, zorder=3)
	elif isinstance(style.color, list):
		# All bars with the same gradient share one gradient that runs across the whole chart.
		group = gradient_groups.setdefault(tuple(style.color), {"paths": [], "bounds": []})
		group["paths"].append(shape.get_path().transformed(shape.get_transform()))
		group["bounds"].append((x0, x1, y0, y1))
	else:
		shape.set_facecolor(style.color)
		ax.add_patch(shape)

	if style.shape == "nyan cat" and bar.is_latest and nyan_cat_image is not None:
		image_height = (y1 - y0) * 1.3
		source_height, source_width = nyan_cat_image.shape[:2]
		image_width = image_height * source_width / source_height
		image_y0 = y0 + ((y1 - y0) - image_height) / 2
		offset = image_width * style.nyan_cat_x_offset / 100
		ax.imshow(nyan_cat_image, extent=(x1 + offset, x1 + offset + image_width, image_y0, image_y0 + image_height),
			origin="upper", aspect="auto", transform=screen, zorder=5)

	if style.shape in {"striped", "board"}:
		draw_stripes(ax, shape, style, x0, y0, x1, y1)


def draw_beer(ax, shape, style: MarkerStyle, x0, y0, x1, y1, rng) -> None:
	screen = IdentityTransform()
	beer_map = matplotlib.colors.LinearSegmentedColormap.from_list("beer_gradient", ["#F3B01F", "#F5C340"])
	beer_gradient = np.tile(beer_map(np.linspace(0, 1, 256))[None, :, :], (256, 1, 1))
	ax.add_patch(shape)
	ax.imshow(beer_gradient, extent=(x0, x1, y0, y1), origin="lower", aspect="auto", interpolation="bilinear",
		transform=screen, clip_path=shape, zorder=3)

	foam_width = (x1 - x0) * 0.28
	if style.beer_foam_max_width is not None:
		foam_width = min(foam_width, style.beer_foam_max_width)
	foam = patches.Rectangle((x1 - foam_width, y0), foam_width, y1 - y0, transform=screen, facecolor="#FCEFCA", edgecolor="none", zorder=4)
	foam.set_clip_path(shape)
	ax.add_patch(foam)

	# Bubbles, more of them towards the bottom of the glass.
	bubble_radius = max(1.2, min(4.0, (y1 - y0) * 0.1))
	bubble_start = x0 + bubble_radius * 2
	bubble_end = x1 - foam_width - bubble_radius * 2
	beer_width = max(0, bubble_end - bubble_start)
	bubble_count = max(1, min(12, round(beer_width / 12)))
	scale = 120
	truncation = -np.expm1(-beer_width / scale)
	positions = np.sort(bubble_start + -scale * np.log(1 - rng.random(bubble_count) * truncation))
	for index, bubble_x in enumerate(positions):
		bubble = patches.Circle(
			(bubble_x, rng.uniform(y0 + bubble_radius, y1 - bubble_radius)),
			bubble_radius * (0.7 + (index % 2) * 0.3),
			transform=screen, facecolor="#FFEEC1", edgecolor="none", zorder=4,
		)
		bubble.set_clip_path(shape)
		ax.add_patch(bubble)


def draw_stripes(ax, shape, style: MarkerStyle, x0, y0, x1, y1) -> None:
	thickness = style.stripe_thickness if style.stripe_thickness is not None else (y1 - y0) / 2.0
	width = max(4.0, thickness * 1.5)
	spacing = width * 2 * np.sqrt(2)
	offsets = np.arange(-y1 + y0, x1 - x0 + y1 - y0, spacing)
	segments = [
		[(x0 + offset - (y1 - y0), y0 - (y1 - y0)), (x0 + offset + 2 * (y1 - y0), y1 + (y1 - y0))]
		for offset in offsets
	]
	if style.shape == "board":
		colors = ["#0057B8"] * len(segments)
	elif isinstance(style.stripe_color, list):
		stripe_map = matplotlib.colors.LinearSegmentedColormap.from_list("stripe_gradient", style.stripe_color)
		colors = stripe_map([np.clip((offset + (y1 - y0) / 2) / (x1 - x0), 0, 1) for offset in offsets])
	else:
		colors = [style.stripe_color] * len(segments)
	stripes = LineCollection(segments, colors=colors, linewidths=width, transform=IdentityTransform(), zorder=6)
	stripes.set_clip_path(shape.get_path(), shape.get_transform())
	ax.add_collection(stripes)


def draw_gradient_groups(ax, gradient_groups: dict) -> None:
	for colors, group in gradient_groups.items():
		shape = patches.PathPatch(MplPath.make_compound_path(*group["paths"]), transform=IdentityTransform(),
			facecolor="none", edgecolor="none", zorder=3)
		bounds = group["bounds"]
		ax.add_patch(shape)
		ax.imshow(
			np.linspace(0, 1, 256)[None, :],
			extent=(min(b[0] for b in bounds), max(b[1] for b in bounds), min(b[2] for b in bounds), max(b[3] for b in bounds)),
			origin="lower", aspect="auto", interpolation="nearest",
			cmap=matplotlib.colors.LinearSegmentedColormap.from_list("activity_gradient", list(colors)),
			vmin=0, vmax=1, transform=IdentityTransform(), clip_path=shape, zorder=3,
		)
