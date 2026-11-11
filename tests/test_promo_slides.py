"""The animated promo slides: find us online, streep your food and the Francken Vrij on paper."""

import unittest
from datetime import datetime
from pathlib import Path

from francken_tv.providers.francken_vrij import FranckenVrijProvider
from francken_tv.providers.francken_vrij_subscribe import FranckenVrijSubscribeProvider
from francken_tv.providers.socials import LINE_SAG, SocialsProvider
from francken_tv.providers.streep import PRODUCTS, TAPS, cursor_keyframes, taps, tiles

NOW = datetime(2026, 11, 11, 12)


class SocialsTest(unittest.TestCase):
	def test_the_pegs_follow_the_line(self):
		cards = SocialsProvider({}).slides(NOW)[0].data["cards"]
		self.assertEqual([card["kind"] for card in cards], ["whatsapp", "linkedin", "instagram", "website"])
		self.assertEqual([card["x"] for card in cards], [12.5, 37.5, 62.5, 87.5])
		self.assertEqual(cards[0]["y"], cards[3]["y"])   # symmetric
		self.assertTrue(cards[0]["y"] < cards[1]["y"] < LINE_SAG)   # lower towards the middle

	def test_an_empty_link_is_left_out(self):
		cards = SocialsProvider({"linkedin": ""}).slides(NOW)[0].data["cards"]
		self.assertEqual([card["kind"] for card in cards], ["whatsapp", "instagram", "website"])
		self.assertEqual([card["i"] for card in cards], [0, 1, 2])


class StreepTest(unittest.TestCase):
	def test_the_count_and_total_add_up(self):
		tap_list = taps()
		self.assertEqual(len(tap_list), len(TAPS))
		self.assertEqual(tap_list[-1]["count"], len(TAPS))
		cents = sum(PRODUCTS[index][2] for index, _ in TAPS)
		self.assertEqual(tap_list[-1]["total"], f"€{cents // 100},{cents % 100:02d}")
		self.assertIsNone(tap_list[-1]["until"])   # the last stays
		self.assertTrue(all(tap["until"] > tap["at"] for tap in tap_list[:-1]))

	def test_only_snacks_with_a_price_are_tapped(self):
		self.assertTrue(all(PRODUCTS[index][2] > 0 for index, _ in TAPS))

	def test_the_tiles_fit_on_the_screen(self):
		for tile in tiles():
			self.assertLessEqual(tile["x"] + tile["w"], 760)
			self.assertLessEqual(tile["y"] + tile["h"], 450)   # above the bottom bar

	def test_the_cursor_moves_forward_in_time(self):
		percents = [frame[0] for frame in cursor_keyframes(tiles(), taps())]
		self.assertEqual(percents, sorted(percents))
		self.assertEqual((percents[0], percents[-1]), (0.0, 100.0))


class FranckenVrijSubscribeTest(unittest.TestCase):
	def test_without_a_pdf_there_is_no_cover(self):
		magazine = FranckenVrijProvider({"folder": "no/such/folder"}, Path("unused"))
		slide = FranckenVrijSubscribeProvider({}, magazine).slides(NOW)[0]
		self.assertIsNone(slide.data["cover"])
		self.assertEqual(slide.data["link"], "https://professorfrancken.nl/profile/francken-vrij")


if __name__ == "__main__":
	unittest.main()
