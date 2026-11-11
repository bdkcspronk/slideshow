"""The Francken pet."""

import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from francken_tv.providers.pet import MAX_DRAIN_PER_DAY, PetCry, PetProvider, advance, clean_name, new_pet, numbered_name

START = datetime(2026, 11, 11, 12, 0)


def run(pet, people, hours, start=START):
	"""Advance minute by minute, like refresh() does."""
	for minute in range(1, int(hours * 60) + 1):
		advance(pet, start + timedelta(minutes=minute), people)


class PetTest(unittest.TestCase):
	def setUp(self):
		self.folder = TemporaryDirectory()
		self.state = Path(self.folder.name) / "pet.json"
		self.people = 0
		self.provider = PetProvider({}, lambda now: self.people, self.state)

	def tearDown(self):
		self.folder.cleanup()

	def hatch(self, name="Bob", now=START):
		slide, _ = self.provider.action("name", [name], now)
		return slide

	def test_more_people_drain_it_faster(self):
		alone, crowd = new_pet("A", 1, START), new_pet("B", 1, START)
		run(alone, 1, 1)
		run(crowd, 10, 1)
		self.assertAlmostEqual(80 - crowd["food"], 10 * (80 - alone["food"]), places=3)

	def test_a_day_drains_at_most_the_cap(self):
		pet = new_pet("A", 1, START)
		pet.update(food=100, fun=100, clean=100)
		run(pet, 30, 10)   # a packed afternoon and evening, until 22:00
		for need in ("food", "fun", "clean"):
			self.assertAlmostEqual(pet[need], 100 - MAX_DRAIN_PER_DAY, places=3)
		run(pet, 30, 8, start=START + timedelta(hours=10))   # past 04:00: a new day, a new allowance
		self.assertLess(pet["fun"], 100 - MAX_DRAIN_PER_DAY)

	def test_three_visits_a_day_keep_it_alive_in_a_crowd(self):
		self.people = 30
		self.hatch()
		for day in range(7):
			for visit in (9, 13, 17):   # each visit taps every button once
				now = START.replace(hour=0) + timedelta(days=day, hours=visit)
				for minute in range(0, 4 * 60, 1):
					self.provider.refresh(now - timedelta(hours=4) + timedelta(minutes=minute))
				for i, action in enumerate(("feed", "play", "clean")):
					self.provider.action(action, [], now + timedelta(seconds=3 * i))
		self.assertIsNone(self.provider.state["pet"]["died"])

	def test_asleep_with_nobody_around(self):
		pet = new_pet("A", 1, START)
		run(pet, 0, 72)   # a weekend
		self.assertEqual((pet["food"], pet["fun"], pet["clean"], pet["died"]), (80, 80, 80, None))

	def test_a_long_gap_counts_as_nobody_there(self):
		pet = new_pet("A", 1, START)
		advance(pet, START + timedelta(days=3), 20)   # the slideshow was off
		self.assertGreater(pet["food"], 65)   # only the first 5 minutes count

	def test_neglected_it_dies(self):
		pet = new_pet("A", 1, START)
		run(pet, 10, 16)   # the day's allowance leaves it at 5...
		self.assertIsNone(pet["died"])
		run(pet, 10, 8, start=START + timedelta(hours=16))   # ...after 04:00 it empties, and two hours later it's dead
		self.assertIsNotNone(pet["died"])
		self.assertEqual(pet["cause"], "died of boredom")   # fun drains fastest

	def test_first_it_asks_for_a_name(self):
		data = self.provider.slides(START)[0].data
		self.assertEqual((data["state"], data["first"]), ("choosing", True))
		self.assertEqual(self.provider.action("next", [], START)[0].data["state"], "naming")
		self.assertEqual(self.provider.action("name", ["  "], START), (None, "Type a name first"))
		slide = self.hatch("BOB THE BLOB", START + timedelta(seconds=5))   # typed on the screen's keyboard
		self.assertEqual((slide.data["name"], slide.data["anim"], slide.data["state"]), ("Bob The Blob", "hatch", "awake"))

	def test_names_are_tidied(self):
		self.assertEqual(clean_name("  <b>Franckie</b>  II "), "bFranckieb II")
		self.assertEqual(clean_name("x" * 40), "x" * 16)
		self.assertEqual(clean_name("Mr. Pickles"), "Mr. Pickles")

	def test_feeding_fills_food_and_survives_a_restart(self):
		self.hatch()
		self.provider.state["pet"]["food"] = 20
		slide, _ = self.provider.action("feed", [], START)
		self.assertEqual(slide.data["anim"], "feed")
		self.assertEqual(slide.data["said"], "Yum!")
		again = PetProvider({}, lambda now: 0, self.state)
		self.assertEqual(again.load()["pet"]["food"], 50)
		self.assertEqual(again.load()["pet"]["name"], "Bob")

	def test_quick_double_taps_count_once(self):
		self.hatch()
		self.provider.state["pet"]["fun"] = 10
		self.provider.action("play", [], START)
		slide, _ = self.provider.action("play", [], START + timedelta(seconds=1))
		self.assertIsNone(slide)
		self.assertAlmostEqual(self.provider.state["pet"]["fun"], 40, places=1)

	def test_full_it_refuses(self):
		self.hatch()
		self.provider.action("clean", [], START)   # 80 + 40 is over the top, still fills
		slide, _ = self.provider.action("clean", [], START + timedelta(seconds=5))
		self.assertEqual(slide.data["anim"], "no")

	def test_a_tap_wakes_it(self):
		self.hatch(now=START - timedelta(hours=1))
		self.assertEqual(self.provider.slides(START)[0].data["state"], "asleep")
		slide, _ = self.provider.action("play", [], START)
		self.assertEqual(slide.data["state"], "awake")

	def test_after_death_name_the_next_one(self):
		self.hatch()
		self.people = 10
		for minute in range(0, 24 * 60, 1):   # a day without care
			self.provider.refresh(START + timedelta(minutes=minute))
		later = START + timedelta(hours=24)
		data = self.provider.slides(later)[0].data
		self.assertEqual((data["state"], data["graves"]), ("dead", 1))
		self.assertIsNone(self.provider.action("feed", [], later)[0])   # can't feed a grave
		data = self.provider.action("bury", [], later)[0].data
		self.assertEqual((data["state"], data["first"], data["last"]), ("choosing", False, "Bob"))
		slide = self.hatch("Alice", later)
		self.assertEqual((slide.data["name"], slide.data["graves"]), ("Alice", 1))

	def test_it_cries_now_and_then_below_half_health(self):
		self.hatch()
		self.people = 5
		self.provider.people = 5
		self.provider.state["pet"].update(health=60)
		self.assertFalse(self.provider.cry_due(START))
		self.provider.state["pet"].update(health=40, food=0)
		announcer = mock.Mock()
		cry = PetCry(self.provider, announcer)
		cries = []
		for second in range(0, 2 * 3600, 10):
			now = START + timedelta(seconds=second)
			self.provider.state["pet"]["health"] = 40   # kept low (and alive) for the test
			cry.tick(now)
			if announcer.play_sound.call_count > len(cries):
				cries.append(now)
		self.assertEqual(cries[0], START)   # right away
		gaps = [(b - a).total_seconds() / 60 for a, b in zip(cries, cries[1:])]
		self.assertTrue(gaps and all(13 <= gap <= 27 for gap in gaps), gaps)   # about every 20 minutes, not all the time

	def test_no_cries_when_asleep(self):
		self.hatch(now=START - timedelta(hours=1))
		self.provider.state["pet"].update(health=30)
		self.assertFalse(self.provider.cry_due(START))

	def test_pick_the_shape_and_colour(self):
		self.provider.action("species", ["octopus"], START)
		data = self.provider.action("color", ["green"], START)[0].data
		self.assertEqual((data["species"], data["color"], data["body"]), ("octopus", "green", "#3fae5a"))
		self.assertIsNone(self.provider.action("species", ["dragon"], START + timedelta(seconds=1))[0])   # not a species
		data = self.provider.action("back", [], START)[0].data
		self.assertEqual(data["state"], "choosing")
		slide = self.hatch("Inky", START + timedelta(seconds=5))
		self.assertEqual((slide.data["species"], slide.data["color"]), ("octopus", "green"))
		again = PetProvider({}, lambda now: 0, self.state)   # after a restart too
		self.assertEqual(again.slides(START)[0].data["species"], "octopus")

	def test_a_name_used_before_gets_a_number(self):
		graves = [{"name": "Bob"}, {"name": "Alice"}, {"name": "bob II", "base": "bob"}]
		self.assertEqual(numbered_name("Bob", []), "Bob")
		self.assertEqual(numbered_name("Alice", graves), "Alice II")
		self.assertEqual(numbered_name("BOB", graves), "BOB III")

	def test_the_next_bob_is_bob_ii(self):
		self.hatch("Bob")
		self.provider.state["pet"]["died"] = START.isoformat()
		self.provider.state["graves"].append({"name": "Bob", "base": "Bob", "hatched": START.isoformat(), "died": START.isoformat()})
		self.provider.action("bury", [], START + timedelta(seconds=5))
		self.assertEqual(self.hatch("Bob II", START + timedelta(seconds=10)).data["name"], "Bob II")   # typed with a number: still II
