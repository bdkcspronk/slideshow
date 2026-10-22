"""Map tiles for maps in slides (static/widgets.js), fetched by the slideshow and kept in data/cache/tiles.

The browser asks /tiles/<z>/<x>/<y>.png (see server.py) instead of the tile server itself: tile
servers want to know which app asks (OpenStreetMap's tile policy) and that tiles are kept rather
than downloaded again, and a cached map keeps working when the internet is slow. Which server is
[maps] tiles in config.toml.
"""

from __future__ import annotations

import logging
import threading
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
