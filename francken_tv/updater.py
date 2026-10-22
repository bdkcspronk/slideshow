"""Keeps the slideshow up to date with GitHub: push from a laptop, and the TV runs it within minutes.

Every few minutes (in a thread of its own) it fetches from the git remote. When there are new
commits it pulls them, but only as a fast-forward and only when the working copy has no changes
of its own (nothing on the TV PC is ever overwritten). Then it runs the tests: if they pass, the
slideshow restarts itself like Ctrl+R; if they fail, it goes back to the version it was running
and doesn't try that commit again. It never restarts during bieruur (the countdown and the song).

Settings: [update] in config.toml.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from datetime import datetime
from typing import Callable

from .config import PROJECT_DIR

log = logging.getLogger(__name__)

TESTS_TIMEOUT_SECONDS = 600


def run(*command: str, timeout: float = 120) -> subprocess.CompletedProcess:
	return subprocess.run(command, cwd=PROJECT_DIR, capture_output=True, text=True, timeout=timeout)


class Updater:
	def __init__(self, settings: dict, now: Callable[[], datetime], busy: Callable[[datetime], bool],
			restart: Callable[[], None], run: Callable[..., subprocess.CompletedProcess] = run) -> None:
		self.enabled = settings.get("auto", True)
		self.check_seconds = settings.get("check_minutes", 10) * 60
		self.now = now          # the slideshow's clock
		self.busy = busy        # e.g. bieruur: don't restart now
		self.restart = restart  # shuts down and starts again (__main__.py)
		self.run = run
		self.bad: str | None = None   # a commit whose tests failed: not tried again
		self.stopped = threading.Event()
		# For /status: the version that runs, and how the last check went.
		self.version = ""
		self.last_check: datetime | None = None
		self.last_result = "not checked yet"

	def start(self) -> None:
		if not self.enabled:
			self.last_result = "off ([update] auto = false)"
			return
		if not (PROJECT_DIR / ".git").exists():
			self.last_result = "off: not a git checkout"
			log.info("Not a git checkout: no automatic updates")
			return
		try:
			self.version = self.git("log", "-1", "--format=%h %s (%cd)", "--date=format:%d-%m %H:%M")
		except Exception as error:
			self.version = f"unknown ({error})"
		log.info("Running %s; checking for updates every %d minutes", self.version, self.check_seconds // 60)
		threading.Thread(target=self.loop, name="updater", daemon=True).start()

	def note(self, result: str) -> None:
		self.last_check, self.last_result = self.now(), result

	def loop(self) -> None:
		while not self.stopped.wait(self.check_seconds):
			try:
				if self.check():
					return   # restarting
			except RuntimeError as error:   # git failed, e.g. no internet: one line, it's tried again later
				self.note(f"failed: {error}")
				log.warning("Checking for updates failed: %s", error)
			except Exception as error:
				self.note(f"failed: {error}")
				log.exception("Checking for updates failed")

	def git(self, *args: str) -> str:
		result = self.run("git", *args)
		if result.returncode != 0:
			raise RuntimeError(f"git {' '.join(args)}: {(result.stderr or result.stdout).strip()}")
		return result.stdout.strip()

	def check(self) -> bool:
		"""Update if there's something new. Returns True when the slideshow is restarting."""
		if self.busy(self.now()):
			self.note("waiting: bieruur")
			return False   # next time
		self.git("fetch", "--quiet")
		upstream = self.git("rev-parse", "@{u}")
		current = self.git("rev-parse", "HEAD")
		if upstream == self.bad:
			self.note(f"not updating to {upstream[:7]}: its tests failed")
			return False
		if upstream == current or self.git("rev-list", "--count", "HEAD..@{u}") == "0":
			self.note("up to date")
			return False   # up to date, or only local commits
		changes = self.git("status", "--porcelain", "--untracked-files=no")
		if changes:
			self.note("not updating: this copy has changes of its own: " + ", ".join(line.split(maxsplit=1)[-1] for line in changes.splitlines()))
			log.warning("Not updating: the working copy has changes of its own (see 'git status')")
			return False
		try:
			self.git("merge", "--ff-only", "--quiet", "@{u}")
		except RuntimeError as error:
			self.note(f"not updating: {error}")
			log.warning("Not updating: %s", error)
			return False
		tests = self.run(sys.executable, "-m", "unittest", "discover", "-q", timeout=TESTS_TIMEOUT_SECONDS)
		if tests.returncode != 0:
			self.git("reset", "--keep", current)   # back to what's running; nothing else touched
			self.bad = upstream
			self.note(f"not updating to {upstream[:7]}: its tests failed (see the log)")
			log.error("Not updating to %s: its tests fail\n%s", upstream[:7], tests.stderr[-2000:])
			return False
		self.note(f"updated to {upstream[:7]}, restarting")
		log.info("Updated to %s: %s", upstream[:7], self.git("log", "-1", "--format=%s"))
		self.restart()
		return True
