"""Streep your food: a reminder to streep the snacks you take on the PC next to the fridge. On a monitor showing
the streep system (its snacks page: a grid of tiles, the name of who's streeping at the bottom) a cursor taps a
few snacks, each tap popping a +1 and adding to the count and the total at the bottom; next to it a fridge draws
itself (templates/slides/streep.html). Replaces the old "Streep your food" poster in media/slides/.

Where the tiles are and when they're tapped is worked out here, in the screen's coordinates (the viewBox of its
SVG, 760 x 520), so the cursor can follow them."""

from __future__ import annotations

from datetime import datetime

from ..slides import Provider, Slide

# The snacks on the screen, as in the streep system (name, the colour of its tile, its price in euro cents; the
# prices are only used for the total of the tapped ones).
PRODUCTS = [
	("Kinder Bueno", "#6b4026", 99), ("Snickers", "#4a2c1d", 0), ("Twix", "#c79a1e", 66), ("KitKat", "#d0121b", 75),
	("Mars", "#1a1a1a", 54), ("Doritos", "#e8701a", 83), ("Pringles", "#b30f28", 0), ("Tuc", "#e6b320", 0),
	("Noodles", "#b8a21f", 68), ("Oreo Rolls", "#1d4fa0", 0), ("Spring roll", "#3a3a3a", 0), ("BIG chocolate", "#3a3a3a", 0),
]
COLUMNS = 4
GRID_X, GRID_Y = 95, 72          # the grid's top left
TILE_W, TILE_H, GAP = 155, 115, 9
# Which tiles are tapped (their index in PRODUCTS) and when (seconds into the slide).
TAPS = [(3, 2.6), (5, 3.8), (3, 5.0), (4, 6.2), (0, 7.4), (2, 8.6), (8, 9.8), (3, 11.0)]
CURSOR_SECONDS = 13.5   # the cursor's animation: every tap, then back to the corner
REST = (600.0, 400.0)   # where the cursor waits


def tiles() -> list[dict]:
	return [{"name": name, "color": color, "x": GRID_X + (i % COLUMNS) * (TILE_W + GAP),
		"y": GRID_Y + (i // COLUMNS) * (TILE_H + GAP), "w": TILE_W, "h": TILE_H} for i, (name, color, _) in enumerate(PRODUCTS)]


def taps() -> list[dict]:
	"""Every tap: the tile, when, and the count and total after it (shown until the next tap: `until`)."""
	result, total = [], 0
	for n, (index, at) in enumerate(TAPS):
		total += PRODUCTS[index][2]
		until = TAPS[n + 1][1] if n + 1 < len(TAPS) else None
		euros = f"€{total // 100},{total % 100:02d}"
		result.append({"tile": index, "at": at, "until": until, "count": n + 1, "total": euros})
	return result


def cursor_keyframes(tile_list: list[dict], tap_list: list[dict]) -> list[tuple[float, float, float, float]]:
	"""(percent of CURSOR_SECONDS, x, y, scale) for the cursor's tip: it goes to each tapped tile and presses it
	(smaller for a moment); before the first and after the last tap it waits in the corner."""
	def percent(seconds: float) -> float:
		return round(seconds / CURSOR_SECONDS * 100, 2)
	frames = [(0.0, *REST, 1.0), (percent(tap_list[0]["at"] - 0.9), *REST, 1.0)]
	for tap in tap_list:
		tile = tile_list[tap["tile"]]
		x, y = tile["x"] + tile["w"] * 0.55, tile["y"] + tile["h"] * 0.6
		frames.append((percent(tap["at"] - 0.35), x, y, 1.0))
		frames.append((percent(tap["at"] - 0.05), x, y, 0.8))
		frames.append((percent(tap["at"] + 0.1), x, y, 1.0))
	frames.append((percent(tap_list[-1]["at"] + 0.9), *REST, 1.0))
	frames.append((100.0, *REST, 1.0))
	return frames


class StreepProvider(Provider):
	name = "streep"
	title = "Streep your food"

	def __init__(self, settings: dict) -> None:
		self.seconds = settings.get("seconds", 14)   # the last snack is tapped after about 11 s

	def slides(self, now: datetime) -> list[Slide]:
		tile_list, tap_list = tiles(), taps()
		return [Slide("streep.html", self.seconds, {
			"tiles": tile_list, "taps": tap_list,
			"cursor": cursor_keyframes(tile_list, tap_list), "cursor_seconds": CURSOR_SECONDS})]
