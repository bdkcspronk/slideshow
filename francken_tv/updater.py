"""Keeps the slideshow up to date with GitHub: push from a laptop, and the TV runs it within minutes.

Every few minutes (in a thread of its own) it fetches from the git remote. When there are new
commits it pulls them, but only as a fast-forward and only when the working copy has no changes
of its own (nothing on the TV PC is ever overwritten). Then it runs the tests: if they pass, the
slideshow restarts itself like Ctrl+R; if they fail, it goes back to the version it was running
and doesn't try that commit again. It never restarts during bieruur (the countdown and the song).

Commits made on the TV PC itself (or pulled by hand) count too: when the commit on disk isn't the one
that's running, the tests run and the slideshow restarts, the same way (not with uncommitted changes).

The rotation settings changed in the menu (config/rotation.json, settings.py) are shared the other way: a minute after
the last change (share_soon(): ten taps make one commit, not ten) the TV commits that one file and pushes it, so every
PC running the slideshow follows it. That commit doesn't restart the slideshow here (it already runs with it). If GitHub
got new commits in the meantime, the TV's rotation commits are replayed on top of them (a rebase; where both changed
rotation.json, the TV's version wins) instead of the fast-forward, and pushed after. Pushing needs the TV PC to be
allowed to push to the repository; until it is, /status says why it failed and the commits wait on the TV.

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
ROTATION = "config/rotation.json"   # the menu's rotation settings: committed and pushed by the TV
SHARE_DELAY_SECONDS = 60            # after the last change in the menu
# Who the TV's own commits are by, so they're recognisable in the history (and it works without a git identity set up).
IDENTITY = ("-c", "user.name=Francken TV", "-c", "user.email=francken-tv@localhost")


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
		self.running: str | None = None   # the commit the slideshow started with
		self.stopped = threading.Event()
		self.lock = threading.Lock()   # one git command at a time: the checks and the sharing run in threads of their own
		self.share_timer: threading.Timer | None = None
		self.started = False
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
			self.running = self.git("rev-parse", "HEAD")
		except Exception as error:
			self.version = f"unknown ({error})"
		log.info("Running %s; checking for updates every %d minutes", self.version, self.check_seconds // 60)
		self.started = True
		threading.Thread(target=self.loop, name="updater", daemon=True).start()
		threading.Thread(target=self.share, name="share-rotation", daemon=True).start()   # a change from before a restart

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

	def share_soon(self) -> None:
		"""The rotation settings changed in the menu: commit and push them a minute after the last change."""
		if not self.started:
			return   # no automatic updates: commit config/rotation.json by hand
		if self.share_timer is not None:
			self.share_timer.cancel()
		self.share_timer = threading.Timer(SHARE_DELAY_SECONDS, self.share)
		self.share_timer.daemon = True
		self.share_timer.start()

	def share(self) -> bool:
		"""Commit config/rotation.json if it changed, then push. Returns whether it committed."""
		try:
			with self.lock:
				if not self.git("status", "--porcelain", "--", ROTATION):
					return False
				before = self.git("rev-parse", "HEAD")
				self.git("add", "--", ROTATION)
				self.git(*IDENTITY, "commit", "--quiet", "-m", "Rotation settings changed on the TV", "--", ROTATION)
				after = self.git("rev-parse", "HEAD")
				if self.running == before:
					self.running = after   # it already runs with these settings: no restart for this commit
				log.info("Committed the rotation settings (%s)", after[:7])
				self.push()
				return True
		except RuntimeError as error:
			self.note(f"sharing the rotation settings failed: {error}")
			log.warning("Sharing the rotation settings failed: %s", error)
			return False

	def push(self) -> None:
		try:
			self.git("push", "--quiet")
			self.note("pushed the rotation settings")
		except RuntimeError as error:   # no internet, or this PC may not push: the commits wait here, tried again next check
			self.note(f"not pushed yet: {error}")
			log.warning("Could not push the rotation settings: %s", error)

	def only_rotation(self) -> bool:
		"""Whether the commits here that GitHub doesn't have only change config/rotation.json."""
		files = set(self.git("log", "--format=", "--name-only", "@{u}..HEAD").split())
		return files <= {ROTATION}

	def check(self) -> bool:
		"""Update if there's something new. Returns True when the slideshow is restarting."""
		with self.lock:
			return self.check_locked()

	def check_locked(self) -> bool:
		if self.busy(self.now()):
			self.note("waiting: bieruur")
			return False   # next time
		current = self.git("rev-parse", "HEAD")
		self.running = self.running or current
		if current != self.running and current != self.bad:   # committed here: no internet needed
			return self.restart_for(current)
		self.git("fetch", "--quiet")
		upstream = self.git("rev-parse", "@{u}")
		if upstream == self.bad:
			self.note(f"not updating to {upstream[:7]}: its tests failed")
			return False
		ahead = upstream != current and self.git("rev-list", "--count", "@{u}..HEAD") != "0"
		rotation_ahead = ahead and self.only_rotation()   # the TV's own rotation commits, not pushed yet
		if upstream == current or self.git("rev-list", "--count", "HEAD..@{u}") == "0":
			if rotation_ahead:
				self.push()
			else:
				self.note("up to date")
			return False   # up to date, or only local commits
		changes = self.git("status", "--porcelain", "--untracked-files=no")
		if changes:
			self.note("not updating: this copy has changes of its own: " + ", ".join(line.split(maxsplit=1)[-1] for line in changes.splitlines()))
			log.warning("Not updating: the working copy has changes of its own (see 'git status')")
			return False
		try:
			if rotation_ahead:   # replay the rotation commits on top of GitHub's; where both changed the file, the TV's wins
				self.git(*IDENTITY, "rebase", "--quiet", "-X", "theirs", "@{u}")   # rewriting commits needs an identity too
			else:
				self.git("merge", "--ff-only", "--quiet", "@{u}")
		except RuntimeError as error:
			if rotation_ahead:
				self.run("git", "rebase", "--abort")
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
		if rotation_ahead:
			self.push()   # the replayed rotation commits; if it fails, the next check after the restart tries again
		self.note(f"updated to {upstream[:7]}, restarting")
		log.info("Updated to %s: %s", upstream[:7], self.git("log", "-1", "--format=%s"))
		self.restart()
		return True

	def restart_for(self, commit: str) -> bool:
		"""A newer commit is on disk than the one running (made or pulled here): restart if it's committed
		completely and its tests pass. Returns True when restarting."""
		changes = self.git("status", "--porcelain", "--untracked-files=no")
		if changes:
			self.note(f"waiting: {commit[:7]} is newer than what runs, but there are uncommitted changes")
			return False
		tests = self.run(sys.executable, "-m", "unittest", "discover", "-q", timeout=TESTS_TIMEOUT_SECONDS)
		if tests.returncode != 0:
			self.bad = commit
			self.note(f"not restarting for {commit[:7]}: its tests failed (see the log)")
			log.error("Not restarting for %s: its tests fail\n%s", commit[:7], tests.stderr[-2000:])
			return False
		self.note(f"{commit[:7]} is newer than what runs: restarting")
		log.info("Restarting for %s: %s", commit[:7], self.git("log", "-1", "--format=%s"))
		self.restart()
		return True
