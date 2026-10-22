"""Updating the slideshow from GitHub by itself."""

import subprocess
import unittest
from datetime import datetime

from francken_tv.updater import Updater

NOW = datetime(2026, 10, 22, 12, 0)


class FakeGit:
	"""Answers git commands like a checkout that's one commit behind GitHub; records what was run."""

	def __init__(self, dirty="", merge_fails=False, tests_fail=False):
		self.head, self.upstream = "aaaaaaa1", "bbbbbbb2"
		self.dirty, self.merge_fails, self.tests_fail = dirty, merge_fails, tests_fail
		self.commands = []

	def __call__(self, *command, timeout=120):
		self.commands.append(command)
		args = command[1:]
		ok = lambda out="": subprocess.CompletedProcess(command, 0, out, "")
		if command[0] != "git":   # the tests
			return subprocess.CompletedProcess(command, 1 if self.tests_fail else 0, "", "FAILED (failures=1)" if self.tests_fail else "")
		if args == ("rev-parse", "@{u}"):
			return ok(self.upstream)
		if args == ("rev-parse", "HEAD"):
			return ok(self.head)
		if args[:2] == ("rev-list", "--count"):
			return ok("0" if self.head == self.upstream else "1")
		if args[0] == "status":
			return ok(self.dirty)
		if args[0] == "merge":
			if self.merge_fails:
				return subprocess.CompletedProcess(command, 128, "", "fatal: Not possible to fast-forward, aborting.")
			self.head = self.upstream
		if args[0] == "reset":
			self.head = args[-1]
		return ok("New slide" if args[0] == "log" else "")

	def ran(self, name):
		return any(command[:2] == ("git", name) for command in self.commands)


class UpdaterTest(unittest.TestCase):
	def updater(self, git, busy=False):
		self.restarts = []
		return Updater({}, lambda: NOW, lambda now: busy, lambda: self.restarts.append(True), run=git)

	def test_new_commits_are_pulled_tested_and_the_slideshow_restarts(self):
		git = FakeGit()
		with self.assertLogs("francken_tv.updater", "INFO"):
			self.assertTrue(self.updater(git).check())
		self.assertEqual((git.head, self.restarts), ("bbbbbbb2", [True]))
		self.assertIn(("git", "merge", "--ff-only", "--quiet", "@{u}"), git.commands)

	def test_up_to_date_nothing_happens(self):
		git = FakeGit()
		git.upstream = git.head
		self.assertFalse(self.updater(git).check())
		self.assertFalse(git.ran("merge"))
		self.assertEqual(self.restarts, [])

	def test_failing_tests_go_back_and_that_commit_is_not_tried_again(self):
		git = FakeGit(tests_fail=True)
		updater = self.updater(git)
		with self.assertLogs("francken_tv.updater", "ERROR"):
			self.assertFalse(updater.check())
		self.assertEqual((git.head, self.restarts), ("aaaaaaa1", []))   # back on the running version
		git.commands.clear()
		self.assertFalse(updater.check())
		self.assertFalse(git.ran("merge"))   # the same broken commit: skipped

	def test_changes_on_the_tv_pc_are_never_overwritten(self):
		git = FakeGit(dirty=" M config/config.toml")
		with self.assertLogs("francken_tv.updater", "WARNING"):
			self.assertFalse(self.updater(git).check())
		self.assertFalse(git.ran("merge"))

	def test_no_fast_forward_no_update(self):
		git = FakeGit(merge_fails=True)
		with self.assertLogs("francken_tv.updater", "WARNING"):
			self.assertFalse(self.updater(git).check())
		self.assertEqual(self.restarts, [])

	def test_not_during_bieruur(self):
		git = FakeGit()
		self.assertFalse(self.updater(git, busy=True).check())
		self.assertEqual(git.commands, [])   # not even a fetch


if __name__ == "__main__":
	unittest.main()
