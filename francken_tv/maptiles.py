"""Map tiles for maps in slides (static/widgets.js), fetched by the slideshow and kept in data/cache/tiles.

The browser asks /tiles/<z>/<x>/<y>.png (see server.py) instead of the tile server itself: tile
servers want to know which app asks (OpenStreetMap's tile policy) and that tiles are kept rather
than downloaded again, and a cached map keeps working when the internet is slow. Which server is
[maps] tiles in config.toml.

With a Google Maps key, the maps use Google's map instead (/tiles/google/<z>/<x>/<y>.png, GoogleTiles
below): it writes every place in English. Over Google's free monthly allowance, or when its API fails,
they go back to OpenStreetMap.
"""

from __future__ import annotations

import html
import json
import logging
import threading
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)

TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
ATTRIBUTION = "&copy; OpenStreetMap contributors"
USER_AGENT = "FranckenTV-slideshow/1.0 (the TV in the T.F.V. 'Professor Francken' room; https://professorfrancken.nl)"
MAX_ZOOM = 19
PARALLEL_DOWNLOADS = 4   # the browser asks many tiles at once: at most this many from the tile server at a time


class TileCache:
	def __init__(self, folder: Path, url: str = TILES) -> None:
		self.folder = folder
		self.url = url
		self.session = requests.Session()   # reused connections: much faster than a new one for each tile
		self.session.headers["User-Agent"] = USER_AGENT
		# As many connections as downloads at a time (more would be opened and thrown away, with a warning each).
		self.session.mount("https://", requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=PARALLEL_DOWNLOADS))
		self.downloads = threading.Semaphore(PARALLEL_DOWNLOADS)

	def get(self, z: int, x: int, y: int) -> Path | None:
		"""The tile's file, downloaded first if needed; None if it doesn't exist or can't be fetched."""
		if not 0 <= z <= MAX_ZOOM or not (0 <= x < 2 ** z and 0 <= y < 2 ** z):
			return None
		path = self.folder / str(z) / str(x) / f"{y}.png"
		if path.exists():
			return path
		# The browser asks several tiles at once, and the server handles them in parallel: a few at a time.
		try:
			with self.downloads:
				if path.exists():   # fetched by another request while this one waited
					return path
				response = self.session.get(self.url.format(z=z, x=x, y=y, s="a"), timeout=15)
		except requests.RequestException as error:
			log.warning("Could not fetch map tile %s/%s/%s: %s", z, x, y, error)
			return None
		if response.status_code != 200 or not response.headers.get("Content-Type", "").startswith("image/"):
			log.warning("Map tile %s/%s/%s: %s", z, x, y, response.status_code)
			return None
		path.parent.mkdir(parents=True, exist_ok=True)
		temporary = path.with_suffix(f".{threading.get_ident()}.tmp")   # its own name, should two threads fetch it
		temporary.write_bytes(response.content)
		temporary.replace(path)
		return path


GOOGLE_API = "https://tile.googleapis.com"
GOOGLE_FREE_TILES = 100_000   # a month, Google's free allowance for its 2D Map Tiles
RETRY_SECONDS = 3600          # after an error, OpenStreetMap for this long before Google is tried again
SAVE_EVERY = 50               # tiles: how often the count is written down (a crash loses at most this many)


class GoogleTiles:
	"""Google's map, with every place in English (OpenStreetMap writes each in its country's own script).

	Used while there's a key, fewer than `monthly_limit` tiles were fetched this month (Google's free
	allowance is GOOGLE_FREE_TILES), and the last error was more than RETRY_SECONDS ago; otherwise the
	maps use OpenStreetMap (usable() is False, and get() returns None). Google's terms don't allow
	keeping its tiles, so they aren't stored: the browser keeps them for as long as Google's cache
	headers say.
	"""

	def __init__(self, key: str, usage_path: Path, monthly_limit: int = GOOGLE_FREE_TILES * 9 // 10,
			clock=time.time) -> None:
		self.key = key
		self.usage_path = usage_path   # {"month": "2026-11", "tiles": 1234}
		self.monthly_limit = monthly_limit
		self.clock = clock
		self.session = requests.Session()
		self.session.mount("https://", requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=PARALLEL_DOWNLOADS))
		self.downloads = threading.Semaphore(PARALLEL_DOWNLOADS)
		self.lock = threading.Lock()
		self.token = ""            # Google's session token: about two weeks valid
		self.token_expiry = 0.0
		self.attribution = "Map data &copy; Google"
		self.failed_at = -RETRY_SECONDS
		self.problem = ""          # the last error, for /status
		self.month, self.used, self.unsaved = self.read_usage()

	def this_month(self) -> str:
		return time.strftime("%Y-%m", time.gmtime(self.clock()))

	def read_usage(self) -> tuple[str, int, int]:
		try:
			usage = json.loads(self.usage_path.read_text())
			return usage["month"], int(usage["tiles"]), 0
		except (OSError, ValueError, KeyError, TypeError):
			return self.this_month(), 0, 0

	def save_usage(self) -> None:
		self.usage_path.parent.mkdir(parents=True, exist_ok=True)
		temporary = self.usage_path.with_suffix(".tmp")
		temporary.write_text(json.dumps({"month": self.month, "tiles": self.used}))
		temporary.replace(self.usage_path)
		self.unsaved = 0

	def usable(self) -> bool:
		with self.lock:
			if self.month != self.this_month():   # a new month: Google's free allowance starts again
				self.month, self.used = self.this_month(), 0
				self.save_usage()
			return bool(self.key) and self.used < self.monthly_limit and self.clock() - self.failed_at >= RETRY_SECONDS

	def get(self, z: int, x: int, y: int) -> tuple[bytes, str, str] | None:
		"""(the tile, its Content-Type, its Cache-Control); None when the maps should use OpenStreetMap."""
		if not (0 <= z <= MAX_ZOOM and 0 <= x < 2 ** z and 0 <= y < 2 ** z) or not self.usable():
			return None
		try:
			with self.downloads:
				token = self.session_token()
				response = self.session.get(f"{GOOGLE_API}/v1/2dtiles/{z}/{x}/{y}",
					params={"session": token, "key": self.key}, timeout=15)
			if response.status_code == 404:   # no tile there (e.g. closer than Google draws): not an error
				return None
			response.raise_for_status()
		except (requests.RequestException, ValueError, KeyError) as error:
			self.fail(error)
			return None
		with self.lock:
			self.used += 1
			self.unsaved += 1
			if self.unsaved >= SAVE_EVERY or self.used >= self.monthly_limit:
				self.save_usage()
			if self.used == self.monthly_limit:
				log.warning("Google map tiles: %d used this month, OpenStreetMap until next month", self.used)
		return (response.content, response.headers.get("Content-Type", "image/png"),
			response.headers.get("Cache-Control", "max-age=86400"))

	def session_token(self) -> str:
		"""Google's session token (map type and language), a new one when it's (nearly) expired."""
		with self.lock:
			if self.token and self.clock() < self.token_expiry - 3600:
				return self.token
			response = self.session.post(f"{GOOGLE_API}/v1/createSession", params={"key": self.key},
				json={"mapType": "roadmap", "language": "en-US", "region": "NL"}, timeout=15)
			response.raise_for_status()
			answer = response.json()
			self.token, self.token_expiry = answer["session"], float(answer["expiry"])
			self.attribution = self.copyright(self.token)
			self.problem = ""
			log.info("Google map tiles: new session")
			return self.token

	def copyright(self, token: str) -> str:
		"""What Google asks to be shown on its map (the whole world's: the map is about the whole world)."""
		try:
			response = self.session.get(f"{GOOGLE_API}/tile/v1/viewport", params={"session": token, "key": self.key,
				"zoom": 2, "north": 85, "south": -85, "west": -179.9, "east": 179.9}, timeout=15)
			response.raise_for_status()
			return html.escape(response.json()["copyright"]) or self.attribution
		except (requests.RequestException, ValueError, KeyError) as error:
			log.warning("Google map tiles: no copyright text (%s)", error)
			return self.attribution

	def warnings(self) -> list[str]:
		"""Why the maps use OpenStreetMap instead of Google right now, for /status."""
		if self.usable():
			return []
		if self.used >= self.monthly_limit:
			return [f"Google map tiles: this month's {self.monthly_limit:,} are used up; OpenStreetMap until next month"]
		return [f"Google map tiles failed ({self.problem}); OpenStreetMap for now, Google is tried again within the hour"]

	def fail(self, error: Exception) -> None:
		with self.lock:
			self.failed_at = self.clock()
			self.token = ""   # it may be the session that's wrong
			self.problem = f"{error}"
		log.warning("Google map tiles failed (%s): OpenStreetMap for the next %d minutes", error, RETRY_SECONDS // 60)
