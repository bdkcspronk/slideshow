"""The menu that Esc opens in the browser (player.js, "The menu"): previews of the slide types in
[shortcuts] (config.toml), every slide type in groups (GROUPS), the settings (settings.py) and the power buttons.

The browser gets everything it shows from menu_data() (GET /api/menu), the groups' previews one group at a time
from group_status() (GET /api/menu/group/<title>), and sends what was chosen to command() (POST /api/menu).
The groups are also the emulator's (tools/emulator.py) and the slides gallery's (tools/slides_gallery.py).
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict
from typing import TYPE_CHECKING

from .settings import SPEEDS

if TYPE_CHECKING:
	from .app import App
	from .slides import Provider

log = logging.getLogger(__name__)

# The slide types in groups: the groups of the menu (Esc) and of the emulator's and the gallery's buttons, in this
# order. A slide belongs to the first group that names its key, or its key up to the number ("news" for news-2);
# anything else lands in "Other". The key is the slide type's name with - for _, or what a slide is called in the
# gallery: poster, event-photo, rain, spotify-lyrics.
GROUPS = [
	("What's on", ["poster", "activities", "practice"]),
	("Today", ["news", "weather", "rain", "buses", "timetable"]),
	("The room", ["presence", "leaderboard", "poll", "streep"]),
	("Puzzles", ["puzzles", "connections", "wordle", "catfishing", "timeguessr"]),
	("Music", ["spotify", "spotify-lyrics", "lyric-video"]),
	("Photos and socials", ["event-photo", "event-photos", "instagram", "socials"]),
	("Committees", ["compucie", "borrelcie", "fotocie"]),
	("Contacts", ["confidential", "ero", "extern"]),
	("Join and buy", ["membership", "socks", "books", "francken-vrij", "francken-vrij-subscribe"]),
	("Fun", ["pet", "quote", "commandments", "xkcd", "graafmachine"]),
	("Full screen", ["bieruur-countdown", "bieruur", "vrijmibo"]),
	("Other", []),
]
# More slides to jump to after a slide type's own (not in the rotation by themselves)
EXTRA = {"weather": [("rain", "Rain warning")], "spotify": [("spotify-lyrics", "Spotify lyrics")],
	"puzzles": [("connections", ""), ("wordle", ""), ("catfishing", ""), ("timeguessr", "")]}
KEYS = {"images": "poster", "event_photos": "event-photo"}   # slide types called differently in GROUPS


def group_of(key: str) -> int:
	for number, (_, keys) in enumerate(GROUPS):
		if key in keys or re.sub(r"-\d+$", "", key) in keys:
			return number
	return len(GROUPS) - 1


def title(provider: Provider) -> str:
	return provider.title or provider.name


def has_slide(provider: Provider, app: App) -> bool:
	try:
		return provider.has_slide(app.clock.now())
	except Exception:
		log.exception("Preview of %s failed", provider.name)
		return False


def channels(app: App) -> list[dict]:
	"""Every slide type of the rotation, and the EXTRA ones after it, as {"name", "label", "group"} (the group's
	number in GROUPS), sorted by group; within a group in the order of the rotation."""
	found = []
	for provider in app.scheduler.providers:
		for name, label in [(provider.name, ""), *EXTRA.get(provider.name, [])]:
			known = app.providers.get(name)
			label = label or (known.title if known else "") or name.replace("_", " ").capitalize()
			found.append({"name": name, "label": label, "group": group_of(KEYS.get(name, name.replace("_", "-")))})
	found.sort(key=lambda channel: channel["group"])   # stable
	return found


def groups(app: App) -> list[dict]:
	"""The groups that have slides: {"title", "channels": [{"name", "label"}]}."""
	every = channels(app)
	return [{"title": title_, "channels": [{"name": c["name"], "label": c["label"]} for c in every if c["group"] == number]}
		for number, (title_, _) in enumerate(GROUPS) if any(c["group"] == number for c in every)]


def slide_for(app: App, name: str):
	"""The slide to show right away for a slide type (or an EXTRA one); None if it has nothing to show."""
	now = app.clock.now()
	if name == "rain":
		return app.providers["weather"].rain_preview(now)
	if name == "spotify-lyrics":
		return app.providers["spotify"].lyrics_slide()
	return app.providers[name].shortcut_slide(now)


def group_status(app: App, group_title: str) -> list[dict] | None:
	"""For each slide of a group: {"name", "available", "empty"}, so the menu can grey out the ones with nothing to
	show right now (and say why). None for an unknown group."""
	for group in groups(app):
		if group["title"] == group_title:
			break
	else:
		return None
	status = []
	for channel in group["channels"]:
		name = channel["name"]
		provider = app.providers.get(name)
		try:
			available = (slide_for(app, name) is not None) if name in ("rain", "spotify-lyrics") else has_slide(provider, app)
		except Exception:
			log.exception("Preview of %s failed", name)
			available = False
		status.append({"name": name, "available": available,
			"empty": getattr(provider, "nothing_to_show", "Nothing to show right now")})
	return status


def menu_data(app: App) -> dict:
	now = app.clock.now()
	app.read_sound()
	puzzles = app.providers.get("puzzles")
	previews = []
	for key, name in app.shortcuts.items():
		provider = app.providers[name]
		previews.append({"key": key, "name": name, "title": title(provider), "available": has_slide(provider, app),
			"empty": provider.nothing_to_show})
	return {
		"previews": previews,
		"groups": groups(app),
		"settings": asdict(app.settings),
		"speeds": SPEEDS,
		"slide_types": [{"name": p.name, "title": title(p)} for p in app.scheduler.providers],
		"puzzles": puzzles.cards(now) if puzzles is not None else [],
		"power": [action for action, command in app.power_commands.items() if command],
	}


def command(app: App, name: str, value) -> str | None:
	"""Carry out a choice from the menu; returns a short message for the screen.
	Raises ValueError for an unknown command or a wrong value."""
	if name == "settings":
		if not isinstance(value, dict):
			raise ValueError("settings needs an object")
		app.change_settings(value)
		return None
	if name == "reset_puzzle":
		puzzles = app.providers.get("puzzles")
		if puzzles is None:
			raise ValueError("there are no puzzles")
		reset = puzzles.reset(value or None)   # no name: all of them
		if not reset:
			raise ValueError(f"unknown puzzle {value!r}")
		return f"Started over: {', '.join(reset)}"
	if name == "reload_devices":
		count = len(app.devices.reload())
		return f"Reloaded {count} devices"
	if name == "power":
		app.power(str(value))
		return "Shutting down…" if value == "shutdown" else "Restarting…"
	raise ValueError(f"unknown menu command {name!r}")
