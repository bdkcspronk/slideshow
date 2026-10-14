"""The local web server that the kiosk browser shows.

	/               the slideshow (templates/player.html + static/player.js)
	/api/next       the next slide as HTML, plus how long to show it
	/api/current    the current slide re-rendered (for slides that update, like the countdown)
	/api/narration  POST: toggle reading quotes aloud
	/api/notice     the latest short message to show in the corner of the screen
	/preview/<name> one slide of a provider or takeover, for checking templates
	/status         what every provider is doing, and the last error
	/files/...      images from media/ and data/cache/ (large images are scaled down)
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import shutil
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

from .config import CACHE_DIR, PROJECT_DIR
from .slides import Slide

if TYPE_CHECKING:
	from .app import App

log = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
SERVED_FOLDERS = [PROJECT_DIR / "media", CACHE_DIR]
RESIZABLE = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def make_templates() -> Environment:
	return Environment(loader=FileSystemLoader(PACKAGE_DIR / "templates"), autoescape=select_autoescape())


class SlideRenderer:
	def __init__(self, app: App) -> None:
		self.app = app
		self.templates = make_templates()
		self.current: Slide | None = None
		self.fitted: dict[tuple[Path, float], Path] = {}

	def render(self, slide: Slide) -> str:
		data = slide.update(self.app.clock.now()) if slide.update else slide.data
		return self.templates.get_template(f"slides/{slide.template}").render(**data)

	def as_json(self, slide: Slide) -> dict:
		return {"html": self.render(slide), "seconds": slide.seconds, "refresh": slide.refresh_seconds}

	def next_slide(self) -> dict:
		slide = self.app.scheduler.next_slide(self.app.clock.now())
		try:
			response = self.as_json(slide)
		except Exception:
			log.exception("Could not render %s", slide.template)
			response = {"html": "", "seconds": 0.1, "refresh": None}   # skip it
		self.current = slide
		if slide.announce:
			self.app.announcer.say_quote(slide.announce)
		return response

	def fitted_image(self, path: Path) -> Path:
		"""A copy of `path` scaled down to the screen size, or `path` itself if it's small enough."""
		key = (path, path.stat().st_mtime)
		if key not in self.fitted:
			width, height = self.app.screen_size
			with Image.open(path) as image:
				if image.width <= width and image.height <= height:
					self.fitted[key] = path
				else:
					digest = hashlib.sha1(f"{path}:{key[1]}".encode()).hexdigest()[:16]
					target = CACHE_DIR / "fitted" / f"{digest}.png"
					if not target.exists():
						target.parent.mkdir(parents=True, exist_ok=True)
						image.thumbnail((width, height), Image.LANCZOS)
						temporary = target.with_suffix(f".{threading.get_ident()}.tmp")
						image.save(temporary, format="PNG")
						temporary.replace(target)
					self.fitted[key] = target
		return self.fitted[key]


class Handler(BaseHTTPRequestHandler):
	server: "Server"

	def do_GET(self) -> None:
		path = unquote(urlparse(self.path).path)
		renderer = self.server.renderer
		if path == "/":
			self.send_html(renderer.templates.get_template("player.html").render())
		elif path == "/api/next":
			self.send_json(renderer.next_slide())
		elif path == "/api/notice":
			self.send_json({"id": self.server.app.notice_id, "text": self.server.app.notice_text})
		elif path == "/api/current":
			slide = renderer.current
			self.send_json(renderer.as_json(slide) if slide else {"html": "", "seconds": 0, "refresh": None})
		elif path.startswith("/preview/"):
			self.send_preview(path.removeprefix("/preview/"))
		elif path == "/status":
			self.send_html(renderer.templates.get_template("status.html").render(app=self.server.app))
		elif path.startswith("/static/"):
			self.send_file(STATIC_DIR / path.removeprefix("/static/"), [STATIC_DIR], cache="no-cache")
		elif path.startswith("/files/"):
			self.send_file(PROJECT_DIR / path.removeprefix("/files/"), SERVED_FOLDERS, fit=True)
		else:
			self.send_error(HTTPStatus.NOT_FOUND)

	def do_POST(self) -> None:
		if urlparse(self.path).path == "/api/narration":
			self.server.app.toggle_quotes()
			self.send_json({"quotes_enabled": self.server.app.announcer.quotes_enabled})
		else:
			self.send_error(HTTPStatus.NOT_FOUND)

	def send_preview(self, name: str) -> None:
		app = self.server.app
		now = app.clock.now()
		slide = None
		if name in app.providers:
			slides = app.providers[name].slides(now)
			slide = slides[0] if slides else None
		elif name in app.takeovers:
			slide = app.takeovers[name].slide(now)
		if slide is None:
			self.send_error(HTTPStatus.NOT_FOUND, f"{name} has no slide right now (see /status)")
			return
		html = self.server.renderer.render(slide)
		self.send_html(self.server.renderer.templates.get_template("preview.html").render(slide_html=html))

	def send_file(self, path: Path, allowed_folders: list[Path], fit: bool = False, cache: str = "max-age=86400") -> None:
		"""cache: media URLs change when the file changes (?v=...), so they can be cached;
		static files (style.css, player.js) are checked again on every load."""
		path = path.resolve()
		if not path.is_file() or not any(path.is_relative_to(folder.resolve()) for folder in allowed_folders):
			self.send_error(HTTPStatus.NOT_FOUND)
			return
		if fit and path.suffix.lower() in RESIZABLE:
			try:
				path = self.server.renderer.fitted_image(path)
			except OSError as error:
				log.warning("Could not scale %s: %s", path, error)
		self.send_response(HTTPStatus.OK)
		self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
		self.send_header("Content-Length", str(path.stat().st_size))
		self.send_header("Cache-Control", cache)
		self.end_headers()
		with open(path, "rb") as file:
			shutil.copyfileobj(file, self.wfile)

	def send_html(self, html: str) -> None:
		self.send_body(html.encode("utf-8"), "text/html; charset=utf-8")

	def send_json(self, data: dict) -> None:
		self.send_body(json.dumps(data).encode("utf-8"), "application/json")

	def send_body(self, body: bytes, content_type: str) -> None:
		self.send_response(HTTPStatus.OK)
		self.send_header("Content-Type", content_type)
		self.send_header("Content-Length", str(len(body)))
		self.send_header("Cache-Control", "no-store")
		self.end_headers()
		self.wfile.write(body)

	def log_message(self, format: str, *args) -> None:
		log.debug(format, *args)


class Server(ThreadingHTTPServer):
	daemon_threads = True

	def __init__(self, app: App, host: str, port: int) -> None:
		super().__init__((host, port), Handler)
		self.app = app
		self.renderer = SlideRenderer(app)
