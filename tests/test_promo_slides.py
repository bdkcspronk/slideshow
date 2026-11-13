"""The animated promo slides: find us online, streep your food and the Francken Vrij on paper."""

import unittest
from datetime import datetime
from pathlib import Path

from francken_tv.providers.fotocie import FotocieProvider
from francken_tv.providers.francken_vrij import FranckenVrijProvider
from francken_tv.providers.francken_vrij_subscribe import FranckenVrijSubscribeProvider
from francken_tv.providers.mscie import MscieProvider
from francken_tv.providers.sjaarscie import SjaarscieProvider
import json
import tempfile

from francken_tv.providers.three import ThreeBenchmarkProvider, ThreeProvider, markdown
from francken_tv.providers.socials import LINE_SAG, SocialsProvider
from francken_tv.providers.streep import PRODUCTS, TAPS, cursor_keyframes, taps, tiles

NOW = datetime(2026, 11, 11, 12)


class FotocieTest(unittest.TestCase):
	def test_one_slide_longer_than_the_animation(self):
		slides = FotocieProvider({}).slides(NOW)
		self.assertEqual([slide.template for slide in slides], ["fotocie.html"])
		self.assertGreater(slides[0].seconds, 2.6)


class SjaarscieTest(unittest.TestCase):
	def test_one_slide_longer_than_the_animation(self):
		slides = SjaarscieProvider({}).slides(NOW)
		self.assertEqual([slide.template for slide in slides], ["sjaarscie.html"])
		self.assertGreater(slides[0].seconds, 5.3)


class MscieTest(unittest.TestCase):
	def test_one_slide_longer_than_the_animation(self):
		slides = MscieProvider({}).slides(NOW)
		self.assertEqual([slide.template for slide in slides], ["mscie.html"])
		self.assertGreater(slides[0].seconds, 6.6)

	def test_every_cap_is_thrown_from_a_hand_above_the_screen_and_is_gone_before_the_name(self):
		for cap in MscieProvider({}).slides(NOW)[0].data["caps"]:
			self.assertGreater(cap["y"], 0)
			self.assertGreater(cap["peak"], cap["y"] + cap["size"])
			self.assertLess(cap["delay"] + 0.4 + cap["seconds"], 5.4)


class ThreeTest(unittest.TestCase):
	def test_every_scene_has_a_widget_scene_that_exists(self):
		slides = ThreeProvider({}).slides(NOW)
		self.assertEqual([slide.data["scene"] for slide in slides], ["simple", "medium", "heavy", "shadows", "triangles", "overdraw", "complex"])
		widgets = (Path(__file__).parent.parent / "francken_tv" / "static" / "widgets.js").read_text()
		for slide in slides:
			self.assertIn(f"\t{slide.data['scene']}(THREE", widgets)

	def test_scenes_can_be_left_out(self):
		slides = ThreeProvider({"scenes": ["complex"]}).slides(NOW)
		self.assertEqual([slide.data["scene"] for slide in slides], ["complex"])


RESULTS = {"when": "2026-11-13T15:00:00Z", "gpu": "Some GPU", "webgl2": True, "screen": "1920x1080", "tests": [
	{"title": "Triangles", "kind": "ramp", "best": "500,000 triangles", "steps": [
		{"label": "500,000 triangles", "fps": 60, "work_ms": 4.2, "p95_ms": 5, "holds": True},
		{"label": "1,000,000 triangles", "fps": 31, "work_ms": 30, "p95_ms": 33, "holds": False}]},
	{"title": "Textures", "kind": "all", "steps": [{"label": "8192x8192 texture", "error": "out | of memory"}]}]}


class ThreeBenchmarkTest(unittest.TestCase):
	def test_the_results_are_saved_as_json_and_markdown(self):
		with tempfile.TemporaryDirectory() as folder:
			json_path, markdown_path = ThreeBenchmarkProvider(Path(folder) / "benchmarks").save(RESULTS, datetime(2026, 11, 13, 15, 4))
			self.assertEqual(json_path.name, "3d-2026-11-13-1504.json")
			self.assertEqual(json.loads(json_path.read_text()), RESULTS)
			text = markdown_path.read_text()
			self.assertIn("**Largest step that holds 60 fps: 500,000 triangles**", text)
			self.assertIn("| 1,000,000 triangles | 31 | 30 | 33 |", text)
			self.assertIn("error: out / of memory", text)   # a | in a cell would break the table

	def test_results_without_tests_are_refused(self):
		with tempfile.TemporaryDirectory() as folder:
			with self.assertRaises(ValueError):
				ThreeBenchmarkProvider(Path(folder)).save({"tests": []}, datetime(2026, 11, 13, 15, 4))
			self.assertEqual(list(Path(folder).iterdir()), [])

	def test_it_is_a_slide_of_its_own_and_in_the_menu(self):
		self.assertEqual([slide.template for slide in ThreeBenchmarkProvider().slides(NOW)], ["three_benchmark.html"])
		from francken_tv import menu
		self.assertEqual(menu.GROUPS[menu.group_of("three-benchmark")][0], "Fun")
		self.assertIn(("three_benchmark", ""), menu.EXTRA["three"])


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
