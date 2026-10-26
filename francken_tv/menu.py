"""The menu that Esc opens in the browser (player.js, "The menu"): previews of the slide types in
[shortcuts] (config.toml), the settings (settings.py) and the power buttons.

The browser gets everything it shows from menu_data() (GET /api/menu) and sends what was chosen
to command() (POST /api/menu).
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import TYPE_CHECKING

from .settings import SPEEDS

if TYPE_CHECKING:
	from .app import App
	from .slides import Provider

log = logging.getLogger(__name__)


def title(provider: Provider) -> str:
	return provider.title or provider.name


def has_slide(provider: Provider, app: App) -> bool:
	try:
		return provider.has_slide(app.clock.now())
	except Exception:
		log.exception("Preview of %s failed", provider.name)
		return False


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
