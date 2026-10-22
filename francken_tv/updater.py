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

	def start(self) -> None:
		if not self.enabled:
			return
		if not (PROJECT_DIR / ".git").exists():
			log.info("Not a git checkout: no automatic updates")
			return
		threading.Thread(target=self.loop, name="updater", daemon=True).start()

	def loop(self) -> None:
		while not self.stopped.wait(self.check_seconds):
			try:
				if self.check():
					return   # restarting
			except Exception:
				log.exception("Checking for updates failed")

	def git(self, *args: str) -> str:
		result = self.run("git", *args)
		if result.returncode != 0:
			raise RuntimeError(f"git {' '.join(args)}: {(result.stderr or result.stdout).strip()}")
		return result.stdout.strip()

	def check(self) -> bool:
		"""Update if there's something new. Returns True when the slideshow is restarting."""
		if self.busy(self.now()):
			return False   # bieruur: next time
		self.git("fetch", "--quiet")
		upstream = self.git("rev-parse", "@{u}")
		current = self.git("rev-parse", "HEAD")
		if upstream == current or upstream == self.bad or self.git("rev-list", "--count", "HEAD..@{u}") == "0":
			return False   # up to date, a commit that failed its tests, or only local commits
		if self.git("status", "--porcelain", "--untracked-files=no"):
			log.warning("Not updating: the working copy has changes of its own (see 'git status')")
			return False
		try:
			self.git("merge", "--ff-only", "--quiet", "@{u}")
		except RuntimeError as error:
			log.warning("Not updating: %s", error)
			return False
		tests = self.run(sys.executable, "-m", "unittest", "discover", "-q", timeout=TESTS_TIMEOUT_SECONDS)
		if tests.returncode != 0:
			self.git("reset", "--keep", current)   # back to what's running; nothing else touched
			self.bad = upstream
			log.error("Not updating to %s: its tests fail\n%s", upstream[:7], tests.stderr[-2000:])
			return False
		log.info("Updated to %s: %s", upstream[:7], self.git("log", "-1", "--format=%s"))
		self.restart()
		return True
