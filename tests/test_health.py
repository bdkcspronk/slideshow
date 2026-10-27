"""/health: what is wrong, in words, and the Instagram token's expiry warning."""

import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from francken_tv import health
from francken_tv.background import RefreshStatus
from francken_tv.providers.instagram import InstagramProvider
from francken_tv.slides import Provider

NOW = datetime(2026, 10, 27, 12)


class Fine(Provider):
	name = "fine"


class Warning(Provider):
	name = "warning"

	def warnings(self, now):
		return ["a login is about to expire"]


def fake_app(providers, errors=None, update=None, backup=None):
	return SimpleNamespace(
		backup_warnings=(lambda now: backup) if backup else None,
		providers={p.name: p for p in providers},
		runner=SimpleNamespace(status={p.name: RefreshStatus(last_error=(errors or {}).get(p.name)) for p in providers}),
		updater=SimpleNamespace(last_result=update) if update else None)


class HealthTest(unittest.TestCase):
	def test_nothing_wrong(self):
		self.assertEqual(health.problems(fake_app([Fine()], update="up to date"), NOW), [])
		self.assertTrue(health.as_text(fake_app([Fine()]), NOW).startswith("OK"))

	def test_a_failed_refresh_points_at_the_manual(self):
		[problem] = health.problems(fake_app([Fine()], errors={"fine": "boom"}), NOW)
		self.assertEqual((problem.what, problem.manual), ("fine", health.BREAKS))
		self.assertIn("boom", problem.detail)

	def test_a_providers_own_warning(self):
		[problem] = health.problems(fake_app([Warning()]), NOW)
		self.assertEqual((problem.detail, problem.manual), ("a login is about to expire", health.ACCOUNTS))

	def test_a_failing_update_is_a_problem(self):
		[problem] = health.problems(fake_app([Fine()], update="not updating: the tests failed"), NOW)
		self.assertEqual(problem.what, "updates")

	def test_a_backup_that_stopped_is_a_problem(self):
		[problem] = health.problems(fake_app([Fine()], backup=["the last backup was 20 days ago"]), NOW)
		self.assertEqual((problem.what, problem.detail), ("backup", "the last backup was 20 days ago"))

	def test_the_text_lists_every_problem(self):
		text = health.as_text(fake_app([Fine(), Warning()], errors={"fine": "boom"}), NOW)
		self.assertIn("2 problem(s)", text)
		self.assertIn("docs/", text)


class InstagramExpiryTest(unittest.TestCase):
	def warnings(self, expires_at):
		with TemporaryDirectory() as folder:
			path = Path(folder) / "instagram.json"
			if expires_at is not None:
				path.write_text(json.dumps({"access_token": "x", "expires_at": expires_at}))
			return InstagramProvider({}, path, Path(folder), 20).warnings(NOW)

	def test_no_warning_while_the_token_is_renewed(self):
		self.assertEqual(self.warnings("2026-12-20T12:00:00"), [])

	def test_no_warning_without_a_token_file_or_expiry(self):
		self.assertEqual(self.warnings(None), [])

	def test_warns_when_the_token_is_close_to_expiring(self):
		[warning] = self.warnings("2026-11-03T12:00:00")
		self.assertIn("expires in 7 days", warning)

	def test_warns_when_the_token_has_expired(self):
		[warning] = self.warnings("2026-10-01T12:00:00")
		self.assertIn("expired", warning)


if __name__ == "__main__":
	unittest.main()
