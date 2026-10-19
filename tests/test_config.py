"""The real config/config.toml loads and every slide type in it exists (a typo there stops the slideshow)."""

import unittest

from francken_tv.app import build_app
from francken_tv.clock import Clock
from francken_tv.config import load_config


class ConfigTest(unittest.TestCase):
	def test_the_real_config_builds_the_app(self):
		config = load_config()
		self.assertIn("puzzles", config)
		app = build_app(config, Clock())
		self.assertIn("poll", app.providers)


if __name__ == "__main__":
	unittest.main()
