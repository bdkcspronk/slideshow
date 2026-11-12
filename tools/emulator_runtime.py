"""The slideshow's server without a network, a real clock, threads or other programs: what runs inside the
emulator page (tools/emulator.py), where Python is started in the browser (Pyodide).

tools/emulator.py fetches today's data on this PC and saves what every slide type then knows with snapshot().
In the browser boot() builds the app again, puts that back, and request() answers what player.js asks
(/api/next, /api/menu, /api/action, /files/..., ...) with the real code of francken_tv/server.py.
"""

from __future__ import annotations

import dataclasses
import enum
import io
import json
import pickle
import subprocess
import threading
import time
from datetime import datetime, timedelta
from email.message import Message
from pathlib import Path
from types import SimpleNamespace

STATE = Path("data/emulator_state.pickle")
INFO = Path("data/emulator.json")       # {"now": the moment the data was fetched for}
NOT_DATA = ("requests", "urllib3", "threading", "_thread", "sqlite3", "subprocess", "jinja2", "socket")

server = None   # set by boot(): .app and .renderer, like francken_tv.server.Server


# ---- what the slide types know: saved on this PC, put back in the browser --------------------------------

class DataPickler(pickle.Pickler):
	"""Only data: no providers, database, sessions or locks (the browser makes its own in build_app)."""

	def reducer_override(self, value):
		from francken_tv.slides import Job, Provider, Takeover
		kind = type(value)
		package = (getattr(kind, "__module__", "") or "").split(".")[0]
		plain = dataclasses.is_dataclass(kind) or isinstance(value, (enum.Enum, tuple))
		if isinstance(value, (Provider, Takeover, Job)) or package in NOT_DATA or (package == "francken_tv" and not plain):
			raise pickle.PicklingError(f"not data: {kind.__name__}")
		return NotImplemented


class DataUnpickler(pickle.Unpickler):
	def find_class(self, module: str, name: str):
		if module.startswith("pathlib."):   # Python 3.13 saves paths as pathlib._local.PosixPath
			module = "pathlib"
		return super().find_class(module, name)


def snapshot(app) -> tuple[bytes, list[str]]:
	"""Every attribute of every provider that is plain data, and the names of those left out. (The takeovers
	only have their settings, and what they showed last, which should start fresh.)"""
	state, left_out = {}, []
	for name, provider in app.providers.items():
		for attribute, value in vars(provider).items():
			buffer = io.BytesIO()
			try:
				DataPickler(buffer, protocol=4).dump(value)
			except Exception:
				left_out.append(f"{name}.{attribute}")
				continue
			state[(name, attribute)] = buffer.getvalue()
	return pickle.dumps(state, protocol=4), left_out


def restore(app, state: bytes) -> None:
	for (name, attribute), value in pickle.loads(state).items():
		if name not in app.providers:
			continue
		try:
			setattr(app.providers[name], attribute, DataUnpickler(io.BytesIO(value)).load())
		except Exception as error:
			print(f"emulator: {name}.{attribute} could not be put back ({error!r})")


# ---- starting -------------------------------------------------------------------------------------------

def offline() -> None:
	"""No threads, other programs or downloads: each fails the way the slideshow already expects
	(nothing in the background, a program that isn't installed, a network that's down)."""
	import requests

	def no_program(*args, **kwargs):
		raise FileNotFoundError("the emulator can't run other programs")

	def no_network(self, method, url, *args, **kwargs):
		raise requests.ConnectionError(f"the emulator has no network ({url})")

	threading.Thread.start = lambda self: None
	subprocess.run = subprocess.Popen = no_program
	requests.Session.request = no_network


def boot() -> None:
	"""In the project folder (the current folder, also on sys.path): build the app at the moment the data was
	fetched for, and give every slide type back what it knew then."""
	global server
	offline()
	from francken_tv.app import build_app
	from francken_tv.clock import Clock
	from francken_tv.config import DEFAULT_CONFIG, load_config
	from francken_tv.server import SlideRenderer

	app = build_app(load_config(DEFAULT_CONFIG), Clock(datetime.fromisoformat(json.loads(INFO.read_text())["now"])))
	restore(app, STATE.read_bytes())
	spotify = app.providers.get("spotify")
	if spotify is not None and getattr(spotify, "playing", None):
		spotify.credentials = lambda: {"refresh_token": "made up"}   # "logged in", like in tools/slides_gallery.py
		spotify.playing.fetched_at = time.monotonic()                # this browser's clock, not the PC's that fetched
	server = SimpleNamespace(app=app, renderer=SlideRenderer(app))


# ---- answering the player -------------------------------------------------------------------------------

def request(method: str, path: str, body: str = "") -> tuple[int, str, bytes]:
	"""What the server would answer: (status, content type, body)."""
	from francken_tv.server import Handler

	class Request(Handler):
		def __init__(self) -> None:   # no socket: the request is already here
			self.server, self.command, self.path = server, method, path
			self.requestline, self.request_version, self.client_address = f"{method} {path} HTTP/1.1", "HTTP/1.1", ("emulator", 0)
			self.headers = Message()
			self.rfile, self.wfile = io.BytesIO(body.encode()), io.BytesIO()
			self.headers["Content-Length"] = str(len(self.rfile.getvalue()))

	answer = Request()
	(answer.do_POST if method == "POST" else answer.do_GET)()
	head, _, content = answer.wfile.getvalue().partition(b"\r\n\r\n")
	lines = head.decode("latin-1").split("\r\n")
	headers = {name.lower(): value for name, _, value in (line.partition(": ") for line in lines[1:])}
	return int(lines[0].split()[1]), headers.get("content-type", "application/octet-stream"), content


def set_time(moment: str) -> None:
	"""Pretend it's this moment ("2026-11-13 15:59:30") from now on, or "now" for the real time; the round
	of slides starts over."""
	app = server.app
	app.clock.offset = timedelta(0) if moment == "now" else datetime.fromisoformat(moment) - datetime.now()
	with app.scheduler.lock:
		app.scheduler.round.clear()


def now() -> str:
	moment = server.app.clock.now()
	return f"{moment:%A} {moment.day} {moment:%B %Y, %H:%M:%S}"
