"""Runs Provider.refresh() and Job.tick() in background threads.

Refreshes and jobs get separate threads, so a slow download can never delay
the bieruur song.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import requests

from .clock import Clock
from .slides import Job, PartsFailed, Provider

log = logging.getLogger(__name__)

RETRY_AFTER_ERROR_SECONDS = 60
AFTER_MIDNIGHT_SECONDS = 30   # every provider refreshes this soon after midnight: a new day's puzzles, ...
NETWORK_WAIT_SECONDS = 120    # at boot, wait at most this long for DNS before the first refreshes
NETWORK_CHECK_HOST = "professorfrancken.nl"
OFFLINE_CHECK_SECONDS = 10    # without the network: how often to check whether it's back


@dataclass
class RefreshStatus:
	last_success: datetime | None = None
	last_error: str | None = None
	next_due: float = 0.0   # time.monotonic()


class BackgroundRunner:
	def __init__(self, clock: Clock, providers: list[Provider], jobs: list[Job]) -> None:
		self.clock = clock
		self.providers = [provider for provider in providers if provider.refresh_seconds]
		self.jobs = jobs
		self.status = {provider.name: RefreshStatus() for provider in self.providers}
		self.stopped = threading.Event()
		self.offline_since: float | None = None   # time.monotonic() when name lookups stopped working

	def start(self) -> None:
		threading.Thread(target=self.refresh_when_online, name="refresh", daemon=True).start()
		threading.Thread(target=self.job_loop, name="jobs", daemon=True).start()

	def stop(self) -> None:
		self.stopped.set()

	def refresh_soon(self, name: str) -> None:
		"""Refresh this provider within a second instead of waiting for its interval."""
		if name in self.status:
			self.status[name].next_due = 0.0

	def refresh_when_online(self) -> None:
		self.wait_for_network()
		self.refresh_loop()

	def wait_for_network(self) -> None:
		"""At boot we start before DNS works (a user service can't wait for network-online.target).

		Without this every provider fails once, logs a warning, and only retries a minute later.
		"""
		deadline = time.monotonic() + NETWORK_WAIT_SECONDS
		waiting_since = None
		while True:
			if not self.online():
				if waiting_since is None:
					waiting_since = time.monotonic()
					log.info("Waiting for the network before refreshing")
				if time.monotonic() > deadline:
					log.warning("No network after %d seconds; refreshing anyway", NETWORK_WAIT_SECONDS)
					return
				if self.stopped.wait(1):
					return
			else:
				if waiting_since is not None:
					log.info("Network is up after %.0f seconds", time.monotonic() - waiting_since)
				return

	@staticmethod
	def online() -> bool:
		"""Whether names can be looked up (DNS): without that, every download fails."""
		try:
			socket.getaddrinfo(NETWORK_CHECK_HOST, 443)
		except OSError:
			return False
		return True

	def network_lost(self) -> bool:
		"""Checked when something is due: is the network gone? Then nothing is refreshed (the slides keep
		what they have) and it's logged once, not as an error per slide type every minute. When it's back,
		everything refreshes right away."""
		if self.online():
			if self.offline_since is not None:
				log.info("The network is back after %.0f minutes: refreshing everything", (time.monotonic() - self.offline_since) / 60)
				self.offline_since = None
				for status in self.status.values():
					status.next_due = 0.0
			return False
		if self.offline_since is None:
			self.offline_since = time.monotonic()
			log.warning("Lost the network (names can't be looked up): refreshing again when it's back")
		return True

	def refresh_loop(self) -> None:
		while not self.stopped.is_set():
			due = any(time.monotonic() >= self.status[provider.name].next_due for provider in self.providers)
			if due and self.network_lost():
				self.stopped.wait(OFFLINE_CHECK_SECONDS)
				continue
			for provider in self.providers:
				status = self.status[provider.name]
				if time.monotonic() < status.next_due:
					continue
				try:
					provider.refresh(self.clock.now())
				except Exception as error:
					if isinstance(error, (requests.RequestException, PartsFailed)):
						# A website that's down or a network hiccup (each part already logged): one line.
						log.warning("Refreshing %s failed: %s", provider.name, error)
					else:
						log.exception("Refreshing %s failed", provider.name)   # probably a bug: with the traceback
					status.last_error = f"{self.clock.now():%H:%M:%S} {error!r}"
					status.next_due = time.monotonic() + min(RETRY_AFTER_ERROR_SECONDS, provider.refresh_seconds)
				else:
					if status.last_error:
						log.info("Refreshing %s works again", provider.name)
					status.last_success = self.clock.now()
					status.last_error = None
					status.next_due = time.monotonic() + min(provider.refresh_seconds, self.seconds_until_midnight() + AFTER_MIDNIGHT_SECONDS)
			self.stopped.wait(1)

	def seconds_until_midnight(self) -> float:
		now = self.clock.now()
		midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
		return (midnight - now).total_seconds()

	def job_loop(self) -> None:
		while not self.stopped.is_set():
			for job in self.jobs:
				try:
					job.tick(self.clock.now())
				except Exception:
					log.exception("Job %s failed", job.name)
			self.stopped.wait(1)
