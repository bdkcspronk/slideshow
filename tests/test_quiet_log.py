"""The same warning at most once an hour (quiet_log.py)."""

import logging
import unittest
from unittest import mock

from francken_tv.quiet_log import OncePerHour


def record(message, level=logging.WARNING, name="francken_tv.info"):
	return logging.LogRecord(name, level, __file__, 1, message, None, None)


class QuietLogTest(unittest.TestCase):
	def test_a_repeated_warning_once_an_hour(self):
		quiet = OncePerHour()
		with mock.patch("francken_tv.quiet_log.time.monotonic", side_effect=[1000, 1060, 1120, 1130, 4700]):
			self.assertTrue(quiet.filter(record("Could not fetch the weather: no internet")))
			self.assertFalse(quiet.filter(record("Could not fetch the weather: no internet")))   # a minute later
			self.assertTrue(quiet.filter(record("Could not fetch the buses: no internet")))      # another message
			self.assertFalse(quiet.filter(record("Could not fetch the buses: no internet")))
			self.assertTrue(quiet.filter(record("Could not fetch the weather: no internet")))    # an hour on: again

	def test_info_messages_always_pass(self):
		quiet = OncePerHour()
		self.assertTrue(quiet.filter(record("Updated", logging.INFO)))
		self.assertTrue(quiet.filter(record("Updated", logging.INFO)))


if __name__ == "__main__":
	unittest.main()
