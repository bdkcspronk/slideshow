"""Wires everything together. To add a slide type: write a provider in providers/,
create it in build_app() below, and add its name to rotation.order in config.toml.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path

from .announcer import Announcer
from .background import BackgroundRunner
from .clock import Clock
from .config import CACHE_DIR, DATA_DIR, project_path
from .devices import DeviceList
from .presence_store import PresenceStore
from .providers.activities import ActivitiesProvider
from .providers.books import BooksProvider
from .providers.catfishing import CatfishingProvider
from .providers.connections import ConnectionsProvider
from .providers.puzzles import PuzzlesProvider
from .providers.spotify import SpotifyProvider
from .providers.wordle import WordleProvider
from .providers.bieruur import BieruurCountdownProvider, BieruurSettings, BieruurSong, BieruurTakeover
from .providers.event_photos import EventPhotosProvider
from .providers.images import ImagesProvider
from .providers.presence import Greeter, LeaderboardProvider, PresenceChartProvider
from .providers.quote import QuoteProvider
from .providers.vrijmibo import VrijmiboTakeover
from .scheduler import Scheduler
from .settings import Settings, load_settings, save_settings
from .system_volume import SystemVolume
from .slides import Job, Provider, Takeover

log = logging.getLogger(__name__)


@dataclass
class App:
	clock: Clock
	announcer: Announcer
	devices: DeviceList
	providers: dict[str, Provider]   # all providers, by name
	takeovers: dict[str, Takeover]
	jobs: list[Job]
	scheduler: Scheduler
	runner: BackgroundRunner
	screen_size: tuple[int, int]
	shortcuts: dict[str, str] = field(default_factory=dict)   # key in the browser -> provider name
	settings: Settings = field(default_factory=Settings)      # changed in the menu (Esc -> Settings)
	settings_path: Path | None = None                         # where they're saved
	power_commands: dict[str, list[str]] = field(default_factory=dict)   # "shutdown"/"restart" -> command
	system_volume: SystemVolume | None = None   # the volume and mute in the settings, also for Spotify
	settings_lock: threading.Lock = field(default_factory=threading.Lock)   # the server handles requests in parallel
	notice_id: int = 0      # the latest on-screen notice, shown by the browser
	notice_text: str = ""

	def notify(self, text: str) -> None:
		"""Show a short message in the corner of the TV screen."""
		self.notice_text = text
		self.notice_id += 1

	def toggle_quotes(self) -> None:
		self.change_settings({"quotes_aloud": not self.settings.quotes_aloud})
		self.notify(f"Reading quotes aloud: {'on' if self.settings.quotes_aloud else 'off'}")

	def change_settings(self, changes: dict) -> None:
		"""Apply and save settings from the menu. Raises ValueError for a wrong value."""
		with self.settings_lock:
			self.settings = self.settings.changed(changes)
			if self.system_volume and self.system_volume.available and ({"volume", "muted"} & changes.keys()):
				self.system_volume.set(self.settings.volume, self.settings.muted)
			self.apply_settings()
			if self.settings_path is not None:
				save_settings(self.settings_path, self.settings)

	def apply_settings(self) -> None:
		settings = self.settings
		self.announcer.mute(settings.muted)
		self.announcer.quotes_enabled = settings.quotes_aloud
		self.announcer.greetings_enabled = settings.greetings
		if not (self.system_volume and self.system_volume.available):
			self.announcer.volume = settings.volume   # no main volume to change: at least the slideshow's own sounds
		self.scheduler.speed = settings.speed
		self.scheduler.hide(set(settings.hidden))

	def read_sound(self) -> None:
		"""Take the volume and mute from the TV PC's sound output: it remembers them itself (also over
		a restart), and they may have been changed with the keyboard's volume keys."""
		state = self.system_volume.get() if self.system_volume else None
		if state is not None:
			with self.settings_lock:
				self.settings = replace(self.settings, volume=state[0], muted=state[1])
				self.announcer.mute(state[1])

	def power(self, action: str) -> None:
		"""Shut down or restart the TV PC (the commands are in config.toml, [power])."""
		command = self.power_commands.get(action)
		if not command:
			raise ValueError(f"no command for {action!r} in config.toml [power]")
		log.warning("Power: %s (%s)", action, " ".join(command))
		try:
			subprocess.Popen(command)
		except OSError as error:
			raise ValueError(f"could not run {command[0]}: {error}") from error

	def reload_devices(self) -> None:
		count = len(self.devices.reload())   # the activity chart uses it the next time it's shown
		self.notify(f"Reloaded {count} devices")


def build_app(config: dict, clock: Clock) -> App:
	display = config.get("display", {})
	seconds = display.get("seconds_per_slide", 8)

	announcer = Announcer(
		config.get("announcer", {}),
		voices_folder=project_path(config.get("announcer", {}).get("voices_folder", "media/voices")),
		cache_folder=CACHE_DIR / "speech",
	)
	presence = config.get("presence", {})
	store = PresenceStore(project_path(presence.get("database", "data/presence.sqlite3")))
	devices = DeviceList(project_path(presence.get("devices", "config/devices.json")))
	bieruur = BieruurSettings(**config.get("bieruur", {}))

	# The puzzles are shown through the Daily puzzles slide, in the order of puzzles.order.
	puzzle_settings = config.get("puzzles", {})
	available_puzzles = {puzzle.name: puzzle for puzzle in [
		ConnectionsProvider(config.get("connections", {}), seconds, DATA_DIR / "puzzles" / "connections.json"),
		WordleProvider(config.get("wordle", {}), seconds, DATA_DIR / "puzzles" / "wordle.json"),
		CatfishingProvider(config.get("catfishing", {}), seconds, DATA_DIR / "puzzles" / "catfishing.json"),
	]}
	puzzles = [available_puzzles[name] for name in puzzle_settings.get("order", list(available_puzzles))]

	all_providers: list[Provider] = [
		ImagesProvider(config.get("images", {}), seconds),
		ActivitiesProvider(config.get("activities", {}), seconds),
		BooksProvider(config.get("books", {}), CACHE_DIR / "books"),
		EventPhotosProvider(config.get("event_photos", {}), CACHE_DIR / "event_photos", seconds),
		PresenceChartProvider(presence, store, devices, project_path("media/nyancat.png"), seconds),
		LeaderboardProvider(config.get("leaderboard", {}), store, devices, seconds),
		QuoteProvider(config.get("quote", {}), DATA_DIR / "quotes.csv", announcer, seconds),
		PuzzlesProvider(puzzle_settings, puzzles, seconds),
		*available_puzzles.values(),
		BieruurCountdownProvider(bieruur),
		SpotifyProvider(config.get("spotify", {}), project_path(config.get("spotify", {}).get("credentials",
			"~/.config/slideshow/spotify.json")), seconds),
	]
	providers = {provider.name: provider for provider in all_providers}
	order = config.get("rotation", {}).get("order", list(providers))
	unknown = [name for name in order if name not in providers]
	if unknown:
		raise SystemExit(f"Unknown slide types in rotation.order: {unknown}. Known: {list(providers)}")
	enabled = [providers[name] for name in order]
	shortcuts = {str(key): name for key, name in config.get("shortcuts", {}).items()}
	unknown = [name for name in shortcuts.values() if name not in providers]
	if unknown:
		raise SystemExit(f"Unknown slide types in shortcuts: {unknown}. Known: {list(providers)}")

	takeovers: list[Takeover] = [BieruurTakeover(bieruur), VrijmiboTakeover(config.get("vrijmibo", {}))]
	jobs: list[Job] = [BieruurSong(bieruur, announcer)]
	jobs.append(Greeter(presence, store, devices, announcer))   # quiet if greetings are off in the settings

	power = config.get("power", {})
	defaults = Settings(
		quotes_aloud=config.get("quote", {}).get("narrate", False),
		greetings=presence.get("greet_arrivals", True),
		volume=config.get("announcer", {}).get("volume", 100),
	)
	app = App(
		clock=clock,
		announcer=announcer,
		devices=devices,
		providers=providers,
		takeovers={takeover.name: takeover for takeover in takeovers},
		jobs=jobs,
		scheduler=Scheduler(enabled, takeovers, config.get("rotation", {}).get("fill_with", "images")),
		# Slide types only reachable by a shortcut still need their downloads.
		runner=BackgroundRunner(clock, enabled + [providers[name] for name in set(shortcuts.values())
			if providers[name] not in enabled], jobs),
		screen_size=(display.get("screen_width", 1920), display.get("screen_height", 1080)),
		shortcuts=shortcuts,
		settings=load_settings(DATA_DIR / "settings.json", defaults),
		settings_path=DATA_DIR / "settings.json",
		power_commands={"shutdown": power.get("shutdown", ["systemctl", "poweroff"]),
			"restart": power.get("restart", ["systemctl", "reboot"])},
		system_volume=SystemVolume(),
	)
	app.read_sound()
	app.apply_settings()
	return app
