"""The local web server that the kiosk browser shows.

	/               the slideshow (templates/player.html + static/player.js)
	/api/next       the next slide as HTML, plus how long to show it
	/api/current    the current slide re-rendered (for slides that update, like the countdown)
	/api/shortcut/<key>  the slide for a shortcut key (see [shortcuts] in config.toml), right away
	/api/slide/<n>  a recent slide again, freshly drawn (going back with the left arrow)
	/api/narration  POST: toggle reading quotes aloud
	/api/menu       the menu (Esc): GET what it shows, POST a choice (see menu.py)
	/api/action     POST: a button on an interactive slide (the puzzle) was clicked
	/api/takeover   whether a takeover should interrupt a paused interactive slide
	/api/notice     the latest short message to show in the corner of the screen
	/preview/<name> one slide of a provider or takeover, for checking templates
	/status         what every provider is doing, and the last error
	/spotify/login  connect the slideshow to a Spotify account (once; see providers/spotify.py)
	/files/...      images from media/ and data/cache/ (large images are scaled down)
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import shutil
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

from . import menu
from .config import CACHE_DIR, PROJECT_DIR
from .slides import Slide

if TYPE_CHECKING:
	from .app import App

log = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
SERVED_FOLDERS = [PROJECT_DIR / "media", CACHE_DIR]
RESIZABLE = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
FITTED_DIR = CACHE_DIR / "fitted"
FITTED_KEEP_SECONDS = 7 * 24 * 3600   # scaled copies not shown for a week are deleted
HOUR = 3600
RECENT_SLIDES = 30   # as many as player.js keeps for the left arrow


def static_version() -> float:
	"""Changes whenever style.css or player.js is edited; the player then reloads itself (see next() in player.js)."""
	return max(file.stat().st_mtime for file in STATIC_DIR.iterdir() if file.is_file())


def clean_fitted(folder: Path, keep_seconds: float = FITTED_KEEP_SECONDS) -> int:
	"""Delete scaled copies that haven't been shown for a while: old versions of edited posters
	and posters that were removed. Copies in use are touched when shown (see fitted_image)."""
	if not folder.is_dir():
		return 0
	cutoff = time.time() - keep_seconds
	removed = 0
	for file in folder.iterdir():
		try:
			if file.stat().st_mtime < cutoff:
				file.unlink()
				removed += 1
		except FileNotFoundError:
			pass
	if removed:
		log.info("Removed %d unused scaled posters", removed)
	return removed


def make_templates() -> Environment:
	return Environment(loader=FileSystemLoader(PACKAGE_DIR / "templates"), autoescape=select_autoescape())


class SlideRenderer:
	def __init__(self, app: App) -> None:
		self.app = app
		self.templates = make_templates()
		self.current: Slide | None = None
		self.recent: dict[int, Slide] = {}   # the last RECENT_SLIDES slides by number, for going back (left arrow)
		self.count = 0
		self.fitted: dict[tuple[Path, float], Path] = {}
		self.last_cleanup = 0.0

	def render(self, slide: Slide) -> str:
		data = slide.update(self.app.clock.now()) if slide.update else slide.data
		return self.templates.get_template(f"slides/{slide.template}").render(**data)

	def as_json(self, slide: Slide) -> dict:
		return {"html": self.render(slide), "seconds": slide.seconds, "refresh": slide.refresh_seconds}

	def next_slide(self) -> dict:
		return self.start(self.app.scheduler.next_slide(self.app.clock.now()))

	def shortcut(self, key: str) -> dict | None:
		"""The slide of the provider under a shortcut key, drawn now; {"message": ...} if it has nothing
		to show (e.g. nobody seen today), None if the key isn't a shortcut."""
		name = self.app.shortcuts.get(key)
		if name is None:
			return None
		provider = self.app.providers[name]
		try:
			slide = provider.shortcut_slide(self.app.clock.now())
		except Exception:
			log.exception("Shortcut to %s failed", name)
			slide = None
		if slide is None:
			return {"message": f"{provider.title or name}: {provider.nothing_to_show}"}
		return self.start(slide)

	def start(self, slide: Slide) -> dict:
		"""Render a slide and make it the current one."""
		try:
			response = self.as_json(slide)
		except Exception:
			log.exception("Could not render %s", slide.template)
			response = {"html": "", "seconds": 0.1, "refresh": None}   # skip it
		response["version"] = static_version()
		self.count += 1
		response["id"] = self.count
		self.recent[self.count] = slide
		self.recent.pop(self.count - RECENT_SLIDES, None)
		self.current = slide
		if slide.announce:
			self.app.announcer.say_quote(slide.announce)
		return response

	def again(self, number: int) -> dict | None:
		"""A recent slide drawn again, now (e.g. going back to the Spotify slide): it becomes the
		current slide, so its once-a-second updates work again. None if it's too long ago."""
		slide = self.recent.get(number)
		if slide is None:
			return None
		self.current = slide
		return {**self.as_json(slide), "id": number}

	def fitted_image(self, path: Path) -> Path:
		"""A copy of `path` scaled down to the screen size, or `path` itself if it's small enough."""
		key = (path, path.stat().st_mtime)
		if key not in self.fitted or not self.fitted[key].exists():   # the cache folder may have been cleared
			width, height = self.app.screen_size
			with Image.open(path) as image:
				if image.width <= width and image.height <= height:
					self.fitted[key] = path
				else:
					digest = hashlib.sha1(f"{path}:{key[1]}".encode()).hexdigest()[:16]
					target = FITTED_DIR / f"{digest}.png"
					if not target.exists():
						target.parent.mkdir(parents=True, exist_ok=True)
						image.thumbnail((width, height), Image.LANCZOS)
						temporary = target.with_suffix(f".{threading.get_ident()}.tmp")
						image.save(temporary, format="PNG")
						temporary.replace(target)
					self.fitted[key] = target
		fitted = self.fitted[key]
		if fitted != path:
			# Mark the copy as in use (at most once an hour), so clean_fitted keeps it.
			if time.time() - fitted.stat().st_mtime > HOUR:
				os.utime(fitted)
			if time.time() - self.last_cleanup > HOUR:
				self.last_cleanup = time.time()
				clean_fitted(FITTED_DIR)
		return fitted


class Handler(BaseHTTPRequestHandler):
	server: "Server"

	def do_GET(self) -> None:
		self.handle_safely(self.get)

	def do_POST(self) -> None:
		self.handle_safely(self.post)

	def handle_safely(self, handler) -> None:
		"""A request that fails is logged and answered with an error; the slideshow keeps running."""
		try:
			handler()
		except (BrokenPipeError, ConnectionResetError):
			pass   # the browser went away (e.g. reloaded); nothing to answer
		except Exception:
			log.exception("Request %s %s failed", self.command, self.path)
			try:
				self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)
			except Exception:
				pass

	def get(self) -> None:
		path = unquote(urlparse(self.path).path)
		renderer = self.server.renderer
		if path == "/favicon.ico":
			self.send_response(HTTPStatus.NO_CONTENT)   # no icon; just keep the browser quiet
			self.end_headers()
		elif path == "/":
			self.send_html(renderer.templates.get_template("player.html").render())
		elif path == "/api/next":
			self.send_json(renderer.next_slide())
		elif path.startswith("/api/shortcut/"):
			slide = renderer.shortcut(path.removeprefix("/api/shortcut/"))
			if slide is None:
				self.send_error(HTTPStatus.NOT_FOUND)
			else:
				self.send_json(slide)
		elif path == "/api/menu":
			self.send_json(menu.menu_data(self.server.app))
		elif path == "/api/takeover":
			now = self.server.app.clock.now()
			due = any(t.interrupts_paused and t.due(now) for t in self.server.app.takeovers.values())
			self.send_json({"due": due})
		elif path == "/api/notice":
			self.send_json({"id": self.server.app.notice_id, "text": self.server.app.notice_text})
		elif path.startswith("/api/slide/") and path.removeprefix("/api/slide/").isdigit():
			again = renderer.again(int(path.removeprefix("/api/slide/")))
			if again is None:
				self.send_error(HTTPStatus.NOT_FOUND)
			else:
				self.send_json(again)
		elif path == "/api/current":
			slide = renderer.current
			self.send_json(renderer.as_json(slide) if slide else {"html": "", "seconds": 0, "refresh": None})
		elif path in ("/spotify/login", "/spotify/callback"):
			self.spotify(path)
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

	def post(self) -> None:
		if urlparse(self.path).path == "/api/action":
			self.send_action()
		elif urlparse(self.path).path == "/api/menu":
			self.send_menu_command()
		elif urlparse(self.path).path == "/api/narration":
			self.server.app.toggle_quotes()
			self.send_json({"quotes_enabled": self.server.app.announcer.quotes_enabled})
		else:
			self.send_error(HTTPStatus.NOT_FOUND)

	def spotify(self, path: str) -> None:
		"""Log in with Spotify: /spotify/login sends the browser to Spotify, which comes back to /spotify/callback."""
		spotify = self.server.app.providers.get("spotify")
		if spotify is None:
			self.send_error(HTTPStatus.NOT_FOUND, "the spotify slide is not set up")
			return
		if path == "/spotify/login":
			url = spotify.login_url()
			if url is None:
				self.send_html(f"<h1>Spotify</h1><p>First put the keys of your Spotify app in <code>{spotify.credentials_path}</code>: "
					'<code>{"client_id": "...", "client_secret": "..."}</code>. See the README, section "Spotify".</p>')
				return
			self.send_response(HTTPStatus.FOUND)
			self.send_header("Location", url)
			self.end_headers()
			return
		query = parse_qs(urlparse(self.path).query)
		if "error" in query:
			self.send_html(f"<h1>Spotify</h1><p>Not connected: {query['error'][0]}. <a href='/spotify/login'>Try again</a>.</p>")
			return
		try:
			spotify.finish_login(query.get("code", [""])[0], query.get("state", [""])[0])
		except Exception as error:
			log.warning("Spotify login failed: %s", error)
			self.send_html(f"<h1>Spotify</h1><p>Not connected: {error}. <a href='/spotify/login'>Try again</a>.</p>")
			return
		# Back to the slideshow after a few seconds (handy when this was opened in the kiosk itself).
		self.send_html("<meta http-equiv='refresh' content='3; url=/'><h1>Spotify</h1><p>Connected! The slideshow "
			"now shows what's playing, and its buttons work. Back to the slideshow in 3 seconds...</p>")

	def read_json(self) -> dict:
		request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
		if not isinstance(request, dict):
			raise ValueError("expected a JSON object")
		return request

	def send_menu_command(self) -> None:
		"""{"command": "settings", "value": {"muted": true}} -> the menu again, and a message."""
		app = self.server.app
		try:
			request = self.read_json()
			message = menu.command(app, str(request.get("command", "")), request.get("value"))
		except ValueError as error:
			self.send_error(HTTPStatus.BAD_REQUEST, str(error))
			return
		self.send_json({"menu": menu.menu_data(app), "message": message})

	def send_action(self) -> None:
		"""{"provider": "connections", "action": "submit", "values": [...]} -> the redrawn slide."""
		try:
			request = self.read_json()
			name, action, values = str(request.get("provider", "")), str(request.get("action", "")), request.get("values", [])
			if not isinstance(values, list):
				raise ValueError("values must be a list")
		except (ValueError, AttributeError) as error:
			self.send_error(HTTPStatus.BAD_REQUEST, str(error))
			return
		provider = self.server.app.providers.get(name)
		if provider is None:
			self.send_error(HTTPStatus.NOT_FOUND)
			return
		try:
			slide, message = provider.action(action, [str(value) for value in values], self.server.app.clock.now())
		except NotImplementedError:
			self.send_error(HTTPStatus.BAD_REQUEST, "this slide is not interactive")
			return
		if slide is not None:
			self.server.renderer.current = slide
		self.send_json({"html": self.server.renderer.render(slide) if slide else None, "message": message})

	def send_preview(self, name: str) -> None:
		app = self.server.app
		now = app.clock.now()
		slide = None
		if name in app.providers:
			slide = app.providers[name].shortcut_slide(now)   # e.g. Spotify also when nothing plays
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
			except Exception:
				log.exception("Could not scale %s; sending the original", path)
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
