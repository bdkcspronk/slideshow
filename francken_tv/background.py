"""Runs Provider.refresh() and Job.tick() in background threads.

Refreshes and jobs get separate threads, so a slow download can never delay
the bieruur song.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime

from .clock import Clock
from .slides import Job, Provider

log = logging.getLogger(__name__)

RETRY_AFTER_ERROR_SECONDS = 60


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

	def start(self) -> None:
		threading.Thread(target=self.refresh_loop, name="refresh", daemon=True).start()
		threading.Thread(target=self.job_loop, name="jobs", daemon=True).start()

	def stop(self) -> None:
		self.stopped.set()

	def refresh_soon(self, name: str) -> None:
		"""Refresh this provider within a second instead of waiting for its interval."""
		if name in self.status:
			self.status[name].next_due = 0.0

	def refresh_loop(self) -> None:
		while not self.stopped.is_set():
			for provider in self.providers:
				status = self.status[provider.name]
				if time.monotonic() < status.next_due:
					continue
				try:
					provider.refresh(self.clock.now())
				except Exception as error:
					log.exception("Refreshing %s failed", provider.name)
					status.last_error = f"{self.clock.now():%H:%M:%S} {error!r}"
					status.next_due = time.monotonic() + min(RETRY_AFTER_ERROR_SECONDS, provider.refresh_seconds)
				else:
					status.last_success = self.clock.now()
					status.last_error = None
					status.next_due = time.monotonic() + provider.refresh_seconds
			self.stopped.wait(1)

	def job_loop(self) -> None:
		while not self.stopped.is_set():
			for job in self.jobs:
				try:
					job.tick(self.clock.now())
				except Exception:
					log.exception("Job %s failed", job.name)
			self.stopped.wait(1)
