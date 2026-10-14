"""Wires everything together. To add a slide type: write a provider in providers/,
create it in build_app() below, and add its name to rotation.order in config.toml.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .announcer import Announcer
from .background import BackgroundRunner
from .clock import Clock
from .config import CACHE_DIR, DATA_DIR, project_path
from .devices import DeviceList
from .presence_store import PresenceStore
from .providers.activities import ActivitiesProvider
from .providers.connections import ConnectionsProvider
from .providers.bieruur import BieruurCountdownProvider, BieruurSettings, BieruurSong, BieruurTakeover
from .providers.event_photos import EventPhotosProvider
from .providers.images import ImagesProvider
from .providers.presence import Greeter, PresenceChartProvider
from .providers.quote import QuoteProvider
from .providers.vrijmibo import VrijmiboTakeover
from .scheduler import Scheduler
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
	notice_id: int = 0      # the latest on-screen notice, shown by the browser
	notice_text: str = ""

	def notify(self, text: str) -> None:
		"""Show a short message in the corner of the TV screen."""
		self.notice_text = text
		self.notice_id += 1

	def toggle_quotes(self) -> None:
		enabled = self.announcer.toggle_quotes()
		self.notify(f"Reading quotes aloud: {'on' if enabled else 'off'}")

	def reload_devices(self) -> None:
		count = len(self.devices.reload())
		self.runner.refresh_soon("presence")
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

	all_providers: list[Provider] = [
		ImagesProvider(config.get("images", {}), seconds),
		ActivitiesProvider(config.get("activities", {}), seconds),
		EventPhotosProvider(config.get("event_photos", {}), CACHE_DIR / "event_photos", seconds),
		PresenceChartProvider(presence, store, devices, CACHE_DIR / "presence_chart.png",
			project_path("media/nyancat.png"), seconds),
		QuoteProvider(config.get("quote", {}), DATA_DIR / "quotes.csv", announcer, seconds),
		ConnectionsProvider(config.get("connections", {}), seconds),
		BieruurCountdownProvider(bieruur),
	]
	providers = {provider.name: provider for provider in all_providers}
	order = config.get("rotation", {}).get("order", list(providers))
	unknown = [name for name in order if name not in providers]
	if unknown:
		raise SystemExit(f"Unknown slide types in rotation.order: {unknown}. Known: {list(providers)}")
	enabled = [providers[name] for name in order]

	takeovers: list[Takeover] = [BieruurTakeover(bieruur), VrijmiboTakeover(config.get("vrijmibo", {}))]
	jobs: list[Job] = [BieruurSong(bieruur, announcer)]
	if presence.get("greet_arrivals", True):
		jobs.append(Greeter(presence, store, devices, announcer))

	return App(
		clock=clock,
		announcer=announcer,
		devices=devices,
		providers=providers,
		takeovers={takeover.name: takeover for takeover in takeovers},
		jobs=jobs,
		scheduler=Scheduler(enabled, takeovers),
		runner=BackgroundRunner(clock, enabled, jobs),
		screen_size=(display.get("screen_width", 1920), display.get("screen_height", 1080)),
	)
