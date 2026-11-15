"""Updating the slideshow from GitHub by itself."""

import json
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
		self.ahead = []              # the files of commits here that GitHub doesn't have
		self.rotation_dirty = False  # config/rotation.json changed and not committed
		self.push_fails = False
		self.commands = []

	def __call__(self, *command, timeout=120):
		self.commands.append(command)
		args = command[1:]
		while args[:1] == ("-c",):   # the TV's identity for its own commits
			args = args[2:]
		ok = lambda out="": subprocess.CompletedProcess(command, 0, out, "")
		fail = lambda error: subprocess.CompletedProcess(command, 1, "", error)
		if command[0] != "git":   # the tests
			return subprocess.CompletedProcess(command, 1 if self.tests_fail else 0, "", "FAILED (failures=1)" if self.tests_fail else "")
		if args == ("rev-parse", "@{u}"):
			return ok(self.upstream)
		if args == ("rev-parse", "HEAD"):
			return ok(self.head)
		if args == ("rev-list", "--count", "@{u}..HEAD"):
			return ok(str(len(self.ahead)))
		if args[:2] == ("rev-list", "--count"):
			return ok("0" if self.head == self.upstream or (self.ahead and not self.behind) else "1")
		if args[:3] == ("status", "--porcelain", "--"):
			return ok(" M config/rotation.json" if self.rotation_dirty else "")
		if args[0] == "status":
			return ok(self.dirty)
		if args[0] == "commit":
			self.rotation_dirty = False
			self.head = "ddddddd4"
			self.ahead.append("config/rotation.json")
		if args[0] == "push":
			if self.push_fails:
				return fail("Permission denied")
			self.upstream, self.ahead = self.head, []
		if args[0] == "rebase" and args[1] != "--abort":
			self.head, self.behind = "eeeeeee5", False
		if args[0] == "merge":
			if self.merge_fails:
				return subprocess.CompletedProcess(command, 128, "", "fatal: Not possible to fast-forward, aborting.")
			self.head = self.upstream
		if args[0] == "reset":
			self.head = args[-1]
		if args[:2] == ("log", "--format="):
			return ok("\n".join(self.ahead))
		return ok("New slide" if args[0] == "log" else "")

	behind = True   # GitHub has commits this copy doesn't

	def ran(self, name):
		return any(command[:2] == ("git", name) for command in self.commands)


class UpdaterTest(unittest.TestCase):
	def updater(self, git, busy=False):
		self.restarts = []
		self.current = Updater({}, lambda: NOW, lambda now: busy, lambda: self.restarts.append(True), run=git)
		return self.current

	def test_new_commits_are_pulled_tested_and_the_slideshow_restarts(self):
		git = FakeGit()
		with self.assertLogs("francken_tv.updater", "INFO"):
			self.assertTrue(self.updater(git).check())
		self.assertEqual((git.head, self.restarts), ("bbbbbbb2", [True]))
		self.assertEqual(self.current.last_result, "updated to bbbbbbb, restarting")
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
		self.assertEqual(self.current.last_result, "not updating: this copy has changes of its own: config/config.toml")   # on /status

	def test_no_fast_forward_no_update(self):
		git = FakeGit(merge_fails=True)
		with self.assertLogs("francken_tv.updater", "WARNING"):
			self.assertFalse(self.updater(git).check())
		self.assertEqual(self.restarts, [])

	def test_a_commit_made_here_restarts_the_slideshow_too(self):
		git = FakeGit()
		git.upstream = git.head
		updater = self.updater(git)
		self.assertFalse(updater.check())   # running aaaaaaa1, nothing new
		git.head = git.upstream = "ccccccc3"   # committed on the TV PC
		git.dirty = " M francken_tv/static/style.css"
		self.assertFalse(updater.check())   # but still editing: wait
		self.assertEqual(self.restarts, [])
		self.assertIn("uncommitted changes", updater.last_result)
		git.dirty = ""
		git.commands.clear()
		with self.assertLogs("francken_tv.updater", "INFO"):
			self.assertTrue(updater.check())
		self.assertEqual(self.restarts, [True])
		self.assertFalse(git.ran("fetch"))   # no internet needed

	def test_a_commit_made_here_with_failing_tests_keeps_the_running_version(self):
		git = FakeGit(tests_fail=True)
		git.upstream = git.head
		updater = self.updater(git)
		updater.check()
		git.head = git.upstream = "ccccccc3"
		with self.assertLogs("francken_tv.updater", "ERROR"):
			self.assertFalse(updater.check())
		git.commands.clear()
		self.assertFalse(updater.check())   # not tested again
		self.assertFalse(any(command[0] != "git" for command in git.commands))
		self.assertEqual(self.restarts, [])

	def test_not_during_bieruur(self):
		git = FakeGit()
		self.assertFalse(self.updater(git, busy=True).check())
		self.assertEqual(git.commands, [])   # not even a fetch


class RotationSharingTest(unittest.TestCase):
	"""The menu's rotation settings (config/rotation.json) are committed and pushed by the TV, so other PCs follow."""

	def updater(self, git):
		self.restarts = []
		updater = Updater({}, lambda: NOW, lambda now: False, lambda: self.restarts.append(True), run=git)
		updater.running = git.head
		return updater

	def test_a_change_is_committed_and_pushed_without_a_restart(self):
		git = FakeGit()
		git.upstream = git.head
		updater = self.updater(git)
		self.assertFalse(updater.share())   # nothing changed
		git.rotation_dirty = True
		with self.assertLogs("francken_tv.updater", "INFO"):
			self.assertTrue(updater.share())
		commit = next(c for c in git.commands if "commit" in c)
		self.assertEqual(commit[-2:], ("--", "config/rotation.json"))   # only that file, whatever else is changed
		self.assertEqual(git.upstream, "ddddddd4")                        # pushed
		self.assertEqual(updater.running, "ddddddd4")
		self.assertFalse(updater.check())                                 # it runs with it already: no restart
		self.assertEqual(self.restarts, [])

	def test_a_push_that_fails_is_tried_again_at_the_next_check(self):
		git = FakeGit()
		git.upstream, git.behind, git.push_fails = git.head, False, True
		updater = self.updater(git)
		git.rotation_dirty = True
		with self.assertLogs("francken_tv.updater", "INFO"):
			updater.share()
		self.assertIn("not pushed yet: ", updater.last_result)   # on /status
		git.push_fails = False
		updater.check()
		self.assertEqual((git.upstream, updater.last_result), ("ddddddd4", "pushed the rotation settings"))

	def test_new_commits_on_github_the_rotation_commit_goes_on_top(self):
		git = FakeGit()   # GitHub is a commit ahead...
		git.push_fails = True
		updater = self.updater(git)
		git.rotation_dirty = True
		with self.assertLogs("francken_tv.updater", "INFO"):
			updater.share()   # ...and the TV has a rotation commit GitHub doesn't
		git.push_fails = False
		with self.assertLogs("francken_tv.updater", "INFO"):
			self.assertTrue(updater.check())
		self.assertTrue(any(c[-5:] == ("rebase", "--quiet", "-X", "theirs", "@{u}") for c in git.commands))
		self.assertFalse(git.ran("merge"))
		self.assertEqual((git.upstream, self.restarts), ("eeeeeee5", [True]))   # pushed, and restarted for GitHub's commit

	def test_other_commits_here_are_not_rebased(self):
		git = FakeGit(merge_fails=True)
		git.ahead = ["francken_tv/app.py"]
		with self.assertLogs("francken_tv.updater", "WARNING"):
			self.assertFalse(self.updater(git).check())
		self.assertFalse(any("rebase" in c for c in git.commands))
		self.assertFalse(git.ran("push"))

	def test_without_automatic_updates_nothing_is_committed(self):
		updater = Updater({"auto": False}, lambda: NOW, lambda now: False, lambda: None, run=FakeGit())
		updater.start()
		updater.share_soon()
		self.assertIsNone(updater.share_timer)


class RotationFileTest(unittest.TestCase):
	def test_the_rotation_is_saved_apart_from_the_other_settings(self):
		from pathlib import Path
		from tempfile import TemporaryDirectory
		from francken_tv.settings import Settings, load_settings, save_settings
		with TemporaryDirectory() as folder:
			settings_path, rotation_path = Path(folder) / "settings.json", Path(folder) / "rotation.json"
			settings = Settings(volume=40, hidden=["quote"], rules={"xkcd": {"every": "5"}})
			self.assertTrue(save_settings(settings_path, settings, rotation_path))
			self.assertFalse(save_settings(settings_path, settings, rotation_path))   # the same again: nothing to share
			self.assertNotIn("hidden", settings_path.read_text())
			self.assertEqual(json.loads(rotation_path.read_text()), {"groups": None, "hidden": ["quote"], "rules": {"xkcd": {"every": "5"}}})
			self.assertEqual(load_settings(settings_path, Settings(), rotation_path), settings)
			# Pulled from GitHub: the rotation file wins over what was saved here before
			rotation_path.write_text('{"hidden": ["pet"]}')
			self.assertEqual(load_settings(settings_path, Settings(), rotation_path).hidden, ["pet"])


if __name__ == "__main__":
	unittest.main()
