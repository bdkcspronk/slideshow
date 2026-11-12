"""The Francken pet."""

import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from francken_tv.providers.pet import MAX_DRAIN_PER_DAY, PetCry, PetProvider, advance, cheer_on_puzzles, clean_name, mood, new_pet, numbered_name, traits
from francken_tv.providers.pet_streep import StreepFeed, listing
from francken_tv.providers.puzzles import PuzzleStatus
from francken_tv.slides import Provider, Slide

START = datetime(2026, 11, 11, 12, 0)


class FakePuzzle(Provider):
	"""A puzzle finished after `moves` moves (solved or lost)."""
	name = "fake"
	title = "Wordle"

	def __init__(self, moves=2, result="solved"):
		self.moves, self.result, self.made = moves, result, 0

	def status(self, now):
		return PuzzleStatus(self.result if self.made >= self.moves else "playing", "")

	def action(self, name, values, now):
		self.made += 1
		return Slide("wordle.html", 20, {"board": self.made}), None


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
		data = self.provider.slides(START)[0].data   # in the slideshow while it waits for a name
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
		self.assertEqual(self.provider.shortcut_slide(START).data["state"], "asleep")
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
		self.assertEqual(again.shortcut_slide(START).data["species"], "octopus")

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

	def test_only_in_the_slideshow_when_it_needs_something(self):
		self.assertEqual(len(self.provider.slides(START)), 1)   # waiting for a name
		self.hatch()
		self.assertEqual(self.provider.slides(START), [])   # all bars at 80 or more
		self.assertIsNotNone(self.provider.shortcut_slide(START))   # the menu's preview still shows it
		self.provider.state["pet"]["fun"] = 49
		self.assertEqual(len(self.provider.slides(START)), 1)
		self.provider.state["pet"].update(fun=80, died=START.isoformat(), cause="starved")
		self.assertEqual(len(self.provider.slides(START)), 1)   # its grave

	def test_the_redrawn_slide_after_a_tap_has_its_animation_once(self):
		self.hatch()
		self.provider.state["pet"]["food"] = 20
		slide, _ = self.provider.action("feed", [], START + timedelta(seconds=5))
		self.assertEqual(slide.update(START + timedelta(seconds=5))["anim"], "feed")   # the server draws it with update()
		self.assertIsNone(slide.update(START + timedelta(seconds=7))["anim"])   # the refresh 2 s later: not again

	def test_finishing_a_puzzle_is_fun_and_the_pet_cheers(self):
		self.hatch()
		self.provider.state["pet"]["fun"] = 20
		puzzle = FakePuzzle()
		cheer_on_puzzles(self.provider, [puzzle])
		slide, _ = puzzle.action("submit", [], START)
		self.assertNotIn("pet_cameo", slide.data)   # not finished yet
		slide, _ = puzzle.action("submit", [], START)
		self.assertEqual(slide.data["board"], 2)   # the puzzle's own data is still there
		self.assertEqual((slide.data["pet_cameo"]["name"], slide.data["pet_cameo"]["plus"]), ("Bob", "+30 fun"))
		self.assertIn("solved Wordle", slide.data["pet_cameo"]["said"])
		self.assertAlmostEqual(self.provider.state["pet"]["fun"], 50, places=1)
		slide, _ = puzzle.action("submit", [], START)   # a tap on the finished puzzle: no second time
		self.assertNotIn("pet_cameo", slide.data)
		self.assertAlmostEqual(self.provider.state["pet"]["fun"], 50, places=1)

	def test_a_lost_puzzle_counts_too(self):
		self.hatch()
		puzzle = FakePuzzle(moves=1, result="lost")
		cheer_on_puzzles(self.provider, [puzzle])
		self.assertIn("hard", puzzle.action("submit", [], START)[0].data["pet_cameo"]["said"])

	def test_no_pet_no_cameo(self):
		puzzle = FakePuzzle(moves=1)
		cheer_on_puzzles(self.provider, [puzzle])   # still waiting for a name
		self.assertNotIn("pet_cameo", puzzle.action("submit", [], START)[0].data)


class FakeResponse:
	def __init__(self, body, status=200):
		self.body, self.status_code = body, status

	def json(self):
		return self.body

	def raise_for_status(self):
		if self.status_code >= 400:
			raise RuntimeError(self.status_code)


class FakeStreepSystem:
	"""The streep system's API: a password, products, and the recent orders (a list the test adds to)."""

	def __init__(self):
		self.orders = [{"id": 1, "member_id": 7, "product_id": 3, "ordered_at": "2026-11-11 11:00:00"}]
		self.logins = 0

	def post(self, url, json, timeout):
		self.logins += 1
		return FakeResponse({"token": "t"} if json["password"] == "secret" else {}, 200 if json["password"] == "secret" else 401)

	def get(self, url, headers, timeout):
		if url.endswith("/members"):
			return FakeResponse({"members": [{"id": "9", "voornaam": "Alice", "achternaam": "Jansen", "bijnaam": ""},
				{"id": "7", "voornaam": "Robert", "achternaam": "Smit", "bijnaam": "Bobby"}]})
		if url.endswith("/products"):
			return FakeResponse({"products": [{"id": "3", "naam": "Twix", "categorie": "Snoep"}, {"id": "4", "naam": "Hertog Jan", "categorie": "Bier"}]})
		return FakeResponse({"orders": list(self.orders)})


class WithStreepSystem(unittest.TestCase):
	"""A pet named Bob, fed by a (fake) streep system."""

	def setUp(self):
		self.folder = TemporaryDirectory()
		folder = Path(self.folder.name)
		(folder / "streep.json").write_text('{"password": "secret"}', encoding="utf-8")
		self.api = FakeStreepSystem()
		self.feed = StreepFeed(folder / "streep.json", self.api)
		self.pet = PetProvider({}, lambda now: 3, folder / "pet.json", self.feed)
		self.pet.action("name", ["Bob"], START)

	def tearDown(self):
		self.folder.cleanup()

	def streep(self, product_id, at):
		self.api.orders.append({"id": len(self.api.orders) + 1, "member_id": 9, "product_id": product_id, "ordered_at": at})


class StreepTest(WithStreepSystem):
	def test_each_streep_feeds_it_one_and_it_says_thank_you(self):
		self.pet.refresh(START)   # the first time: the orders already there only count as seen
		self.assertIsNone(self.pet.overlay(START))
		food, fun = self.pet.state["pet"]["food"], self.pet.state["pet"]["fun"]
		self.streep(3, "2026-11-11 12:00:10")   # a Twix: food
		self.streep(4, "2026-11-11 12:00:20")   # a Hertog Jan: fun, not food
		self.pet.refresh(START + timedelta(seconds=30))
		self.assertAlmostEqual(self.pet.state["pet"]["food"], food + 1, delta=0.3)   # minus a little drain in those 30 s
		self.assertAlmostEqual(self.pet.state["pet"]["fun"], fun + 1, delta=0.3)
		shown = self.pet.overlay(START + timedelta(seconds=31))
		self.assertEqual(shown["template"], "pet_cameo.html")
		cameo = shown["data"]["pet_cameo"]
		self.assertEqual((cameo["plus"], cameo["said"], cameo["name"]), ("+1 food +1 fun", "Thank you for the Twix! And thank you Alice for the Hertog Jan! *hic*", "Bob"))
		self.assertIsNone(self.pet.overlay(START + timedelta(seconds=36)))   # once
		self.pet.refresh(START + timedelta(seconds=60))   # the same orders again: nothing new
		self.assertIsNone(self.pet.overlay(START + timedelta(seconds=61)))
		self.assertEqual(self.api.logins, 1)

	def test_without_the_password_file_nothing_happens(self):
		self.feed.credentials = Path(self.folder.name) / "missing.json"
		self.assertEqual(self.feed.poll(START), [])

	def test_listing(self):
		self.assertEqual(listing(["Twix"]), "Twix")
		self.assertEqual(listing(["Twix", "Mars", "Cola", "Tuc", "Bueno"]), "Twix, Mars, Cola and 2 more")


class SoberTest(WithStreepSystem):
	def test_beer_makes_it_less_sober_and_water_helps(self):
		self.pet.refresh(START)
		for i in range(10):
			self.streep(4, f"2026-11-11 12:01:{i:02d}")   # ten Hertog Jans
		self.pet.refresh(START + timedelta(seconds=30))
		pet = self.pet.state["pet"]
		self.assertAlmostEqual(pet["sober"], 70, delta=0.5)
		self.assertIn("*hic*", self.pet.overlay(START + timedelta(seconds=31))["data"]["pet_cameo"]["said"])
		pet["sober"] = 30
		data = self.pet.shortcut_slide(START + timedelta(seconds=32)).data
		self.assertGreater(data["traits"]["drunk"], 0.5)
		self.assertEqual(data["mood"], "okay")   # the face still follows the emptiest need (sober 30), drunk is an amount on top
		slide, _ = self.pet.action("water", [], START + timedelta(seconds=33))
		self.assertEqual(slide.data["anim"], "water")
		self.assertAlmostEqual(pet["sober"], 55, delta=0.5)

	def test_it_sobers_up_by_itself_and_dies_of_drink_when_left_at_zero(self):
		pet = new_pet("A", 1, START)
		pet["sober"] = 50
		run(pet, 0, 5)   # asleep: sleeping it off
		self.assertAlmostEqual(pet["sober"], 70, places=1)
		pet["sober"] = 0
		run(pet, 3, 3, start=START + timedelta(hours=5))   # nobody gives it water
		self.assertEqual(pet["cause"], "drank itself to death")

	def test_a_pet_from_before_the_sober_bar(self):
		self.pet.state["pet"].pop("sober")
		self.assertEqual(self.pet.shortcut_slide(START).data["bars"][3]["key"], "sober")


	def test_only_alcohol_is_thanked_by_name(self):
		self.pet.refresh(START)
		self.streep(4, "2026-11-11 12:00:10")   # Alice: a beer
		self.api.orders.append({"id": 99, "member_id": 7, "product_id": 4, "ordered_at": "2026-11-11 12:00:12"})   # Bobby: a beer
		self.api.orders.append({"id": 100, "member_id": 42, "product_id": 4, "ordered_at": "2026-11-11 12:00:14"})   # someone unknown
		self.pet.refresh(START + timedelta(seconds=30))
		said = self.pet.overlay(START + timedelta(seconds=31))["data"]["pet_cameo"]["said"]
		self.assertEqual(said, "Thank you Alice and Bobby for the 3 Hertog Jan! *hic*")   # nickname, or else first name
		self.assertNotIn("Jansen", said)
		self.api.orders.append({"id": 101, "member_id": 7, "product_id": 3, "ordered_at": "2026-11-11 12:01:00"})   # Bobby: a Twix
		self.pet.refresh(START + timedelta(seconds=60))
		self.assertEqual(self.pet.overlay(START + timedelta(seconds=61))["data"]["pet_cameo"]["said"], "Thank you for the Twix!")


class TraitsTest(unittest.TestCase):
	def pet(self, **needs):
		return {"food": 100, "fun": 100, "clean": 100, "sober": 100, "health": 100} | needs

	def test_the_face_only_follows_the_emptiest_need(self):
		self.assertEqual(mood(self.pet()), "happy")
		self.assertEqual(mood(self.pet(fun=40)), "okay")
		self.assertEqual(mood(self.pet(clean=10, sober=5)), "sad")

	def test_nothing_shows_when_it_is_fine(self):
		self.assertEqual(traits(self.pet()), {"sick": 0, "drunk": 0, "dirt": 0})

	def test_the_amounts_grow_and_stack(self):
		both = traits(self.pet(clean=25, sober=30, health=55))
		self.assertEqual(both["dirt"], 0.75)
		self.assertEqual(both["drunk"], 0.75)
		self.assertEqual(both["sick"], 0.5)
		self.assertEqual(traits(self.pet(food=0))["sick"], 1)
