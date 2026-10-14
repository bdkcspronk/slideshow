import unittest
from datetime import date, datetime

from francken_tv.providers.connections import ConnectionsProvider, parse_puzzle

NOW = datetime(2026, 10, 14, 12, 0)


def fake_puzzle(day: str) -> dict:
	"""Same shape as the NYT JSON: four categories, easiest first, each card with a grid position."""
	categories = []
	for group in range(4):
		cards = [{"content": f"W{group}{i}", "position": (i * 4 + group)} for i in range(4)]
		categories.append({"title": f"GROUP {group}", "cards": cards})
	return {"status": "OK", "id": 1, "print_date": day, "categories": categories}


def group(number: int) -> list[str]:
	return [f"W{number}{i}" for i in range(4)]


def loaded_provider() -> ConnectionsProvider:
	provider = ConnectionsProvider({}, 8)
	provider.fetch = lambda day: parse_puzzle(fake_puzzle(day.isoformat()))
	provider.refresh(NOW)
	return provider


class PuzzleTest(unittest.TestCase):
	def test_parse_puts_words_in_grid_order(self):
		puzzle = parse_puzzle(fake_puzzle("2026-10-14"))
		self.assertEqual(puzzle.day, date(2026, 10, 14))
		self.assertEqual(puzzle.words[:5], ["W00", "W10", "W20", "W30", "W01"])
		self.assertEqual(puzzle.groups[0], ("GROUP 0", group(0)))

	def test_downloads_today_and_yesterday_once(self):
		provider = ConnectionsProvider({}, 8)
		fetched = []
		provider.fetch = lambda day: fetched.append(day) or parse_puzzle(fake_puzzle(day.isoformat()))
		provider.refresh(NOW)
		provider.refresh(NOW)
		self.assertEqual(fetched, [date(2026, 10, 14), date(2026, 10, 13)])
		[slide] = provider.slides(NOW)
		self.assertEqual(len(slide.data["words"]), 16)
		self.assertEqual(slide.data["yesterday"].day, date(2026, 10, 13))

	def test_no_slide_without_todays_puzzle(self):
		self.assertEqual(ConnectionsProvider({}, 8).slides(NOW), [])


class GameTest(unittest.TestCase):
	def setUp(self):
		self.provider = loaded_provider()

	def submit(self, words):
		slide, message = self.provider.action("submit", words, NOW)
		return slide.data, message

	def test_correct_group_moves_to_the_top(self):
		data, message = self.submit(group(2))
		self.assertIsNone(message)
		self.assertEqual(data["groups"], [(2, "GROUP 2", group(2))])
		self.assertEqual(len(data["words"]), 12)
		self.assertEqual(data["mistakes_left"], 4)

	def test_one_away_keeps_the_selection(self):
		guess = group(0)[:3] + [group(1)[0]]
		data, message = self.submit(guess)
		self.assertEqual(message, "One away...")
		self.assertEqual((data["selected"], data["shake"], data["mistakes_left"]), (guess, True, 3))

	def test_same_wrong_guess_twice_costs_no_extra_mistake(self):
		guess = group(0)[:2] + group(1)[:2]
		self.assertEqual(self.submit(guess)[1], "Not quite")
		data, message = self.submit(guess)
		self.assertEqual((message, data["mistakes_left"]), ("Already guessed!", 3))

	def test_four_mistakes_reveal_the_answers(self):
		for number in range(4):
			data, message = self.submit(group(0)[:2] + group(1)[number:number + 1] + group(2)[number:number + 1])
		self.assertEqual(message, "Next time!")
		self.assertTrue(data["finished"])
		self.assertEqual([level for level, _, _ in data["groups"]], [0, 1, 2, 3])
		self.assertEqual(data["words"], [])

	def test_winning(self):
		for number in (3, 1, 0):
			self.submit(group(number))
		data, message = self.submit(group(2))
		self.assertEqual((message, data["finished"]), ("Perfect!", True))
		self.assertEqual([level for level, _, _ in data["groups"]], [3, 1, 0, 2])   # in the order found

	def test_progress_is_kept_until_a_new_puzzle(self):
		self.submit(group(1))
		self.assertEqual(len(self.provider.slides(NOW)[0].data["groups"]), 1)   # the slideshow came back round
		tomorrow = datetime(2026, 10, 15, 9, 0)
		self.provider.refresh(tomorrow)
		self.assertEqual(self.provider.slides(tomorrow)[0].data["groups"], [])

	def test_shuffle_keeps_the_same_words(self):
		before = self.provider.slides(NOW)[0].data["words"]
		slide, _ = self.provider.action("shuffle", [], NOW)
		self.assertEqual(sorted(slide.data["words"]), sorted(before))


if __name__ == "__main__":
	unittest.main()
